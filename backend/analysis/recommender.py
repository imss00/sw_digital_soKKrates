"""
역할 A — A-3/A-4/A-5. 추천 엔진
RSS 기사 추천 / Spotify 무드 분석 / FAISS 유사도 검색.

[Railway 주의]
FAISS 인덱스를 파일로 저장하면 재배포 시 사라짐.
인메모리 인덱스 방식으로 구현한다 (호출마다 당일 벡터로 재구성).
장기 주간 누적이 필요하면 DB에 벡터를 쌓고 부팅 시 로드하는 방식으로 확장.
"""
import json
from datetime import date, datetime, timedelta, timezone

import faiss
import numpy as np
import feedparser
import requests
from sqlalchemy.orm import Session

from backend.models.unified_document import UnifiedDocument
from backend.models.spotify_history import SpotifyHistory
from backend.analysis.embedder import embed_texts

KST = timezone(timedelta(hours=9))

RSS_FEEDS = [
    # 한국 종합 뉴스 (한국인 사용자용 — 2026-06 기준 RSS 제공 확인)
    "https://www.yna.co.kr/rss/news.xml",                      # 연합뉴스 종합
    "https://www.khan.co.kr/rss/rssdata/total_news.xml",      # 경향신문 종합
    "https://rss.donga.com/total.xml",                         # 동아일보 종합
    # 한국 IT/기술 뉴스
    "https://rss.etnews.com/Section901.xml",                   # 전자신문 IT
    "https://it.donga.com/feeds/rss/",                         # IT동아
    # 글로벌 기술 뉴스 (한·영 혼합 추천을 위해 유지)
    "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    "https://www.theverge.com/rss/index.xml",
]


# ── RSS 수집 ──────────────────────────────────────────────────

def collect_rss_articles() -> list[dict]:
    """RSS 피드에서 최근 기사 수집. 피드당 최대 10개.

    Uses `requests` to fetch feed content and then `feedparser.parse()` on the bytes
    to avoid Python SSL certificate verification issues in some environments.
    """
    # 일부 매체(The Verge 등)는 기본 python-requests UA를 봇으로 차단 → 브라우저 UA 사용
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PaperBackAgent/1.0)"}
    articles = []
    for feed_url in RSS_FEEDS:
        try:
            resp = requests.get(feed_url, timeout=10, headers=headers)
            if resp.status_code != 200 or not resp.content:
                continue
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:10]:
                articles.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:300],
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                })
        except Exception:
            continue
    return articles


# ── FAISS 유사도 검색 ──────────────────────────────────────────

def build_faiss_index(vectors: np.ndarray) -> faiss.Index:
    """당일 벡터로 인메모리 FAISS 인덱스 생성."""
    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)  # 내적 = 정규화 시 코사인 유사도
    normalized = vectors.copy()
    faiss.normalize_L2(normalized)
    index.add(normalized)
    return index


def recommend_articles(
    user_vectors: np.ndarray,
    article_embeddings: np.ndarray,
    articles: list[dict],
    top_k: int = 3,
) -> list[dict]:
    """
    사용자 관심사 벡터 평균(centroid)으로 기사 임베딩과 유사도 비교 → 상위 top_k 반환.

    article_embeddings: embedder.embed_texts([a['title'] + ' ' + a['summary'] for a in articles])
    """
    centroid = user_vectors.mean(axis=0, keepdims=True).astype(np.float32)
    article_vecs = article_embeddings.astype(np.float32)

    faiss.normalize_L2(centroid)
    faiss.normalize_L2(article_vecs)

    scores = np.dot(article_vecs, centroid.T).flatten()
    top_indices = np.argsort(scores)[-top_k:][::-1]

    return [
        {**articles[i], "relevance_score": float(scores[i])}
        for i in top_indices
    ]


# ── Spotify 무드 분석 ──────────────────────────────────────────

def analyze_yesterday_mood(user_id: int, target_date: date, db: Session) -> dict:
    """어제 Spotify 청취 기록에서 평균 valence/energy + 주요 장르 계산."""
    day_start = datetime.combine(target_date - timedelta(days=1), datetime.min.time()).replace(tzinfo=KST)
    day_end = day_start + timedelta(days=1)

    records = (
        db.query(SpotifyHistory)
        .filter(
            SpotifyHistory.user_id == user_id,
            SpotifyHistory.played_at >= day_start,
            SpotifyHistory.played_at < day_end,
        )
        .all()
    )

    if not records:
        return {"status": "skip", "reason": "no spotify data"}

    valences = [r.valence for r in records if r.valence is not None]
    energies = [r.energy for r in records if r.energy is not None]
    genres = [g for r in records for g in (r.genres or [])]

    avg_valence = float(np.mean(valences)) if valences else None
    avg_energy = float(np.mean(energies)) if energies else None
    top_genre = max(set(genres), key=genres.count) if genres else None

    return {
        "status": "ok",
        "avg_valence": avg_valence,
        "avg_energy": avg_energy,
        "top_genre": top_genre,
        "mood": "bright" if avg_valence and avg_valence > 0.5 else "calm",
        "track_count": len(records),
    }


# ── 핵심 테마 요약 (역할 B가 core_theme 키로 소비) ─────────────────

DEFAULT_CORE_THEME = "특별한 관심사가 감지되지 않았습니다."


def summarize_core_theme(interest_clusters: list[dict], docs: list) -> str:
    """
    하루 활동(클러스터/문서)을 한 줄 핵심 테마로 요약한다.
    역할 B(journal_composer)가 analysis_result["core_theme"]로 받아 회고/기사소개의 재료로 쓴다.

    날조 금지: 실제 클러스터 대표 텍스트만 근거로 요약한다.
    Gemini 호출 실패/데이터 없음 시 결정적(deterministic) 폴백으로 안전하게 떨어진다.
    """
    # 1) 요약 근거 텍스트 수집: 클러스터 우선(doc_count 큰 순), 없으면 문서 content_text
    snippets: list[str] = []
    for c in sorted(interest_clusters, key=lambda c: c.get("doc_count", 0), reverse=True):
        snippets.extend(c.get("keywords", []))
    if not snippets:
        snippets = [getattr(d, "title", None) or (d.content_text or "")[:50] for d in docs]
    snippets = [s.strip() for s in snippets if s and s.strip()]

    if not snippets:
        return DEFAULT_CORE_THEME

    # 결정적 폴백 문구 (Gemini 실패 시 사용): 대표 토막 몇 개를 이어붙임
    deterministic = " · ".join(dict.fromkeys(snippets[:5]))

    # 2) Gemini로 자연스러운 한 줄 테마 생성 (근거 텍스트만 제공 → 날조 방지)
    try:
        from google import genai

        client = genai.Client()
        joined = "\n".join(f"- {s}" for s in snippets[:15])
        prompt = (
            "다음은 사용자가 하루 동안 남긴 디지털 활동의 대표 조각들입니다.\n"
            "이를 관통하는 핵심 관심사를 자연스러운 한국어 한 문장(15자~40자)으로 요약하세요.\n"
            "제공된 내용에 없는 사실을 지어내지 말고, 마크다운/따옴표 없이 문장만 출력하세요.\n\n"
            f"{joined}"
        )
        resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        theme = (resp.text or "").strip().strip('"').strip()
        return theme or deterministic
    except Exception:
        return deterministic


# ── 통합 추천 실행 ──────────────────────────────────────────────

def run_recommendation(user_id: int, target_date: date, db: Session) -> dict:
    """
    역할 A 전체 추천 파이프라인 진입점.
    clusterer.run_clustering() 완료 후 호출.

    Returns:
        analysis_result dict — 역할 B의 journal_composer.py가 그대로 받아간다.
    """
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=KST)
    day_end = day_start + timedelta(days=1)

    docs = (
        db.query(UnifiedDocument)
        .filter(
            UnifiedDocument.user_id == user_id,
            UnifiedDocument.occurred_at >= day_start,
            UnifiedDocument.occurred_at < day_end,
            UnifiedDocument.embedding_json.isnot(None),
        )
        .all()
    )

    labels = np.array([doc.cluster_id if doc.cluster_id is not None else -1 for doc in docs])
    from backend.analysis.clusterer import extract_cluster_keywords
    interest_clusters = extract_cluster_keywords(docs, labels)

    # 핵심 테마 한 줄 요약 → 역할 B가 core_theme 키로 받아 회고/기사소개에 주입
    core_theme = summarize_core_theme(interest_clusters, docs)

    mood = analyze_yesterday_mood(user_id, target_date, db)

    # RSS 기사 추천 구현 활성화
    try:
        articles = collect_rss_articles()
        if articles:
            article_texts = [a.get('title', '') + ' ' + a.get('summary', '') for a in articles]
            # 임베딩은 외부 API 호출이므로 예외 안전하게 처리
            article_embeddings = np.array(embed_texts(article_texts), dtype=np.float32)
            user_vectors = np.array([json.loads(d.embedding_json) for d in docs], dtype=np.float32)
            if user_vectors.size and article_embeddings.size:
                recommended_articles = recommend_articles(user_vectors, article_embeddings, articles)
            else:
                recommended_articles = []
        else:
            recommended_articles = []
    except Exception:
        # 실패 시 안전하게 빈 리스트 반환
        recommended_articles = []

    # TODO: Spotify 플레이리스트 검색 구현 (A-5)
    music_recommendation = mood  # TODO: Spotify Search API로 실제 플레이리스트 링크 추가

    # 역할 A 최종 산출물: 구조화 JSON (역할 B journal_composer가 받아 기사를 쓴다).
    # 기존 반환 키는 그대로 유지하고 "structured" 키만 추가 → B 계약 보존.
    from backend.analysis.journal_input import assemble_journal_input
    structured = assemble_journal_input(
        user_id,
        target_date,
        db,
        mood_summary=mood,
        recommended_articles=recommended_articles,
    )

    return {
        "core_theme": core_theme,
        "interest_clusters": interest_clusters,
        "recommended_articles": recommended_articles,
        "music_recommendation": music_recommendation,
        "mood_summary": mood,
        "structured": structured,
    }
