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
from sqlalchemy.orm import Session

from backend.models.unified_document import UnifiedDocument
from backend.models.spotify_history import SpotifyHistory

KST = timezone(timedelta(hours=9))

RSS_FEEDS = [
    # TODO: 팀원이 원하는 피드 추가
    "https://feeds.feedburner.com/zdnetkorea",
    "https://www.bloter.net/feed",
    "https://news.hada.io/rss",  # GeekNews
]


# ── RSS 수집 ──────────────────────────────────────────────────

def collect_rss_articles() -> list[dict]:
    """RSS 피드에서 최근 기사 수집. 피드당 최대 10개."""
    articles = []
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
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

    mood = analyze_yesterday_mood(user_id, target_date, db)

    # TODO: RSS 기사 추천 구현
    # articles = collect_rss_articles()
    # article_texts = [a['title'] + ' ' + a['summary'] for a in articles]
    # article_embeddings = np.array(embed_texts(article_texts), dtype=np.float32)
    # user_vectors = np.array([json.loads(d.embedding_json) for d in docs], dtype=np.float32)
    # recommended_articles = recommend_articles(user_vectors, article_embeddings, articles)
    recommended_articles = []  # TODO

    # TODO: Spotify 플레이리스트 검색 구현 (A-5)
    music_recommendation = mood  # TODO: Spotify Search API로 실제 플레이리스트 링크 추가

    return {
        "interest_clusters": interest_clusters,
        "recommended_articles": recommended_articles,
        "music_recommendation": music_recommendation,
        "mood_summary": mood,
    }
