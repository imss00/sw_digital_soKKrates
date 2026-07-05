"""
역할 A — 구조화 JSON 어셈블러.
embedder → clusterer → recommender 까지 끝난 뒤, 역할 A 파이프라인의
'최종 산출물'로 역할 B(journal_composer)가 받아 기사를 쓰게 할 구조화 JSON을 만든다.

설계 규칙(요약):
1) Graceful degradation: 구조화 원본값 있으면 사용 → 없으면 content_text 파싱 → 그래도 없으면 placeholder.
2) 날조 금지: 데이터로 뒷받침 안 되는 값은 채우지 않고 _available:false + placeholder로 둔다.
   각 섹션에 "_source"/"_available" 플래그를 달아 역할 B가 placeholder를 사실로 오해하지 않게 한다.
3) Spotify 제약: audio_features / /recommendations 는 신규 앱에서 403. 메타데이터(album/year/label)는
   반드시 살아있는 Spotify search + album 엔드포인트로 실값 조회한다. 모델 기억으로 지어내지 않는다.
4) photo: 현재 장면 라벨(LABEL_DETECTION) grounding 불가 → _available:false 로 비운다.
"""
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.models.unified_document import UnifiedDocument
from backend.models.spotify_history import SpotifyHistory
from backend.models.youtube_history import YouTubeHistory

KST = timezone(timedelta(hours=9))


# ── EN→KO 변환 테이블 (데이터 있을 때만 적용) ────────────────────────

GENRE_KO: dict[str, str] = {
    "classical": "클래식",
    "modern classical": "모던 클래식",
    "neoclassical": "신고전주의",
    "minimal": "미니멀",
    "ambient": "앰비언트",
    "lo-fi": "로파이",
    "jazz": "재즈",
    "blues": "블루스",
    "soul": "소울",
    "r-n-b": "알앤비",
    "rnb": "알앤비",
    "indie": "인디",
    "folk": "포크",
    "country": "컨트리",
    "pop": "팝",
    "k-pop": "케이팝",
    "hip-hop": "힙합",
    "rap": "랩",
    "rock": "록",
    "electronic": "일렉트로닉",
    "dance": "댄스",
    "edm": "EDM",
    "metal": "메탈",
    "piano": "피아노",
}

# YouTube Data API category_id → 한국어 카테고리명
YOUTUBE_CATEGORY_KO: dict[int, str] = {
    1: "영화/애니메이션",
    2: "자동차",
    10: "음악",
    15: "동물",
    17: "스포츠",
    19: "여행/이벤트",
    20: "게임",
    22: "인물/블로그",
    23: "코미디",
    24: "엔터테인먼트",
    25: "뉴스/정치",
    26: "노하우/스타일",
    27: "교육",
    28: "과학기술",
    29: "비영리/사회운동",
}


def _to_ko_genre(genre: str | None) -> str | None:
    """장르명이 영어면 한국어로 변환. 매핑에 없으면 원문 유지."""
    if not genre:
        return None
    g = genre.lower().strip()
    for key, ko in GENRE_KO.items():
        if key in g:
            return ko
    return genre


def _format_watch_time(total_sec: int | None) -> str | None:
    """초 → 'N시간 M분' / 'M분'. 0 또는 None이면 None."""
    if not total_sec or total_sec <= 0:
        return None
    minutes = total_sec // 60
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"{hours}시간 {mins}분"
    return f"{mins}분"


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=KST)
    return start, start + timedelta(days=1)


# ── photo 섹션 ───────────────────────────────────────────────────

def build_photo_section(user_id: int, target_date: date, db: Session) -> dict:
    """
    현재 사진 분석은 스크린샷 OCR(TEXT_DETECTION)만이라 '노을/해안선' 같은 장면 라벨이 없다.
    photo_keywords/mood/category를 채울 근거가 없으므로 날조하지 않고 비운다.
    (Phase 1에 LABEL_DETECTION 추가 시 해소되며, 이번 작업 범위 밖.)
    """
    return {
        "_available": False,
        "_source": "none",
        "_reason": "사진 장면 라벨(LABEL_DETECTION) 미수집 — 키워드 grounding 불가",
        "photo_keywords": [],
        "photo_mood": None,
        "recommend_category": None,
    }


# ── youtube 섹션 ─────────────────────────────────────────────────

def build_youtube_section(user_id: int, target_date: date, db: Session) -> dict:
    """
    3단 폴백:
      1) YouTubeHistory 원본(tags / category_id / duration_sec) 사용
      2) 없으면 unified_documents(youtube) content_text 파싱
      3) 그래도 없으면 placeholder + _available:false
    """
    day_start, day_end = _day_bounds(target_date)

    yt_records = (
        db.query(YouTubeHistory)
        .filter(
            YouTubeHistory.user_id == user_id,
            YouTubeHistory.watched_at >= day_start,
            YouTubeHistory.watched_at < day_end,
        )
        .all()
    )

    section: dict = {
        "_available": False,
        "_source": "none",
        "youtube_keywords": [],
        "top_category": None,
        "total_watch_time": None,
        "repeat_type": None,
    }

    if yt_records:
        section["_source"] = "youtube_history"
        section["_available"] = True

        # 키워드: 원본 tags 빈도 집계
        tag_counter: Counter[str] = Counter()
        for r in yt_records:
            for t in (r.tags or []):
                if t and t.strip():
                    tag_counter[t.strip()] += 1
        if tag_counter:
            section["youtube_keywords"] = [t for t, _ in tag_counter.most_common(8)]

        # top_category: 최빈 category_id → 한국어명
        cat_ids = [r.category_id for r in yt_records if r.category_id is not None]
        if cat_ids:
            top_id = Counter(cat_ids).most_common(1)[0][0]
            section["top_category"] = YOUTUBE_CATEGORY_KO.get(top_id, f"카테고리 {top_id}")

        # total_watch_time: duration_sec 합 (있을 때만)
        durations = [r.duration_sec for r in yt_records if r.duration_sec]
        watch_time = _format_watch_time(sum(durations)) if durations else None
        if watch_time:
            section["total_watch_time"] = watch_time
        else:
            section["total_watch_time"] = "측정 불가"
            section["_watch_time_available"] = False

        # repeat_type: 같은 채널 반복 시청 여부로 가벼운 추정 (근거 있을 때만)
        channels = [r.channel_name for r in yt_records if r.channel_name]
        if channels:
            ch_top, ch_cnt = Counter(channels).most_common(1)[0]
            if ch_cnt >= 2:
                section["repeat_type"] = f"{ch_top} 반복 시청"
        return section

    # 폴백: unified_documents(youtube) content_text 파싱
    yt_docs = (
        db.query(UnifiedDocument)
        .filter(
            UnifiedDocument.user_id == user_id,
            UnifiedDocument.source == "youtube",
            UnifiedDocument.occurred_at >= day_start,
            UnifiedDocument.occurred_at < day_end,
        )
        .all()
    )
    if yt_docs:
        section["_source"] = "unified_documents"
        section["_available"] = True
        section["total_watch_time"] = "측정 불가"
        section["_watch_time_available"] = False

        # content_text 끝의 "Tags: a, b, c" 패턴에서 태그 추출 (normalize_youtube 포맷)
        tag_counter = Counter()
        kw_counter: Counter[str] = Counter()
        for d in yt_docs:
            # 이미 keywords 컬럼이 채워졌으면 그것도 활용
            for k in (d.keywords or []):
                if k and k.strip():
                    kw_counter[k.strip()] += 1
            m = re.search(r"Tags:\s*(.+)$", d.content_text or "")
            if m:
                for t in m.group(1).split(","):
                    t = t.strip()
                    if t:
                        tag_counter[t] += 1
        if tag_counter:
            section["youtube_keywords"] = [t for t, _ in tag_counter.most_common(8)]
        elif kw_counter:
            section["youtube_keywords"] = [k for k, _ in kw_counter.most_common(8)]

    return section


# ── music 섹션 ───────────────────────────────────────────────────

def _spotify_client(user_id: int, db: Session):
    """살아있는 Spotify 토큰으로 spotipy 클라이언트 생성. 실패 시 None."""
    try:
        import spotipy
        from backend.models.user import User
        from backend.collectors.spotify_collector import _refresh_spotify_token

        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.spotify_refresh_token:
            return None
        token = _refresh_spotify_token(user, db)
        if not token:
            return None
        return spotipy.Spotify(auth=token)
    except Exception:
        return None


def _album_metadata(sp, track: dict) -> dict:
    """
    track(검색 결과)에서 album/year를 뽑고, album 엔드포인트로 label을 실조회.
    어떤 필드도 모델 기억으로 지어내지 않는다. 조회 실패 필드는 None.
    """
    album = track.get("album") or {}
    album_name = album.get("name")
    release_date = album.get("release_date") or ""
    year = release_date[:4] if release_date else None

    label = None
    album_id = album.get("id")
    if album_id:
        try:
            full_album = sp.album(album_id)
            label = full_album.get("label")
        except Exception:
            label = None

    return {"album": album_name, "year": year, "label": label}


def build_music_section(user_id: int, target_date: date, db: Session, mood_summary: dict) -> dict:
    """
    yesterday_tracks: 어제(target_date) SpotifyHistory 집계 (재생 횟수 포함).
    rec_track_1/2: 청취 패턴(top 장르/아티스트)으로 후보를 만들고, 메타데이터는
                   Spotify search + album 엔드포인트로 실값 조회. 토큰/네트워크 실패 시 _available:false.
    rec_reason: valence/energy 대신 장르·아티스트 빈도 요약.
    """
    yday_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=KST)
    yday_end = yday_start + timedelta(days=1)

    records = (
        db.query(SpotifyHistory)
        .filter(
            SpotifyHistory.user_id == user_id,
            SpotifyHistory.played_at >= yday_start,
            SpotifyHistory.played_at < yday_end,
        )
        .all()
    )

    section: dict = {
        "_available": False,
        "_source": "none",
        "yesterday_tracks": [],
        "rec_track_1": None,
        "rec_track_2": None,
        "rec_reason": None,
        "_rec_source": "none",
    }

    if not records:
        section["rec_reason"] = "어제 Spotify 청취 기록이 없어 추천 근거를 만들 수 없습니다."
        return section

    section["_available"] = True
    section["_source"] = "spotify_history"

    # 1) yesterday_tracks: (track, artist) 재생 횟수 집계
    play_counter: Counter[tuple[str, str]] = Counter()
    for r in records:
        play_counter[(r.track_name or "", r.artist_name or "")] += 1
    section["yesterday_tracks"] = [
        {"title": title, "artist": artist, "count": cnt}
        for (title, artist), cnt in play_counter.most_common(10)
    ]

    # 2) 청취 패턴 요약 (장르 빈도 → rec_reason, EN→KO)
    genres = [g for r in records for g in (r.genres or [])]
    top_genres_raw = [g for g, _ in Counter(genres).most_common(3)] if genres else []
    top_genres_ko = [x for x in (_to_ko_genre(g) for g in top_genres_raw) if x]

    top_artists = [a for a, _ in Counter(r.artist_name for r in records if r.artist_name).most_common(3)]

    reason_parts = []
    if top_genres_ko:
        reason_parts.append(f"장르 {' · '.join(dict.fromkeys(top_genres_ko))}")
    if top_artists:
        reason_parts.append(f"아티스트 {', '.join(top_artists[:2])}")
    mood_name = mood_summary.get("mood") if isinstance(mood_summary, dict) else None
    mood_ko = {"bright": "밝고 경쾌한", "calm": "고요·힐링"}.get(mood_name, None)
    if mood_ko:
        reason_parts.append(f"{mood_ko} 계열로 분류됨(장르 기반 추정)")
    section["rec_reason"] = (
        "어제 청취 패턴이 " + ", ".join(reason_parts) + "." if reason_parts
        else "어제 청취 패턴 요약(장르 정보 부족)."
    )

    # 3) rec_track_1/2: Spotify search + album 으로 실 메타데이터 조회
    sp = _spotify_client(user_id, db)
    if sp is None:
        section["_rec_source"] = "fallback"
        section["_rec_available"] = False
        return section

    yday_titles = {t for t, _ in play_counter.keys()}
    queries: list[str] = []
    # 후보 쿼리: top 장르 우선, 없으면 top 아티스트
    for g in top_genres_raw:
        queries.append(f'genre:"{g}"')
    for a in top_artists:
        queries.append(f'artist:"{a}"')

    recs: list[dict] = []
    seen_titles: set[str] = set()
    try:
        for q in queries:
            if len(recs) >= 2:
                break
            try:
                res = sp.search(q=q, type="track", limit=10)
            except Exception:
                continue
            for tr in res.get("tracks", {}).get("items", []):
                title = tr.get("name")
                if not title or title in yday_titles or title in seen_titles:
                    continue
                artists = ", ".join(a["name"] for a in tr.get("artists", []))
                meta = _album_metadata(sp, tr)
                recs.append({
                    "title": title,
                    "artist": artists,
                    "album": meta["album"],
                    "year": meta["year"],
                    "label": meta["label"],
                })
                seen_titles.add(title)
                if len(recs) >= 2:
                    break
    except Exception:
        pass

    if recs:
        section["_rec_source"] = "spotify_search"
        section["_rec_available"] = True
        section["rec_track_1"] = recs[0]
        section["rec_track_2"] = recs[1] if len(recs) > 1 else None
    else:
        section["_rec_source"] = "fallback"
        section["_rec_available"] = False

    return section


# ── headline 섹션 (마지막 롤업) ──────────────────────────────────

def build_headline(photo: dict, youtube: dict, music: dict, mood_summary: dict) -> dict:
    """다른 섹션을 다 채운 뒤 파생하는 순수 롤업."""
    yt_keywords = youtube.get("youtube_keywords") or []
    photo_keywords = photo.get("photo_keywords") or []

    # music_genre: 추천 reason보다 안정적으로, mood_summary.top_genre를 EN→KO
    music_genre = None
    if isinstance(mood_summary, dict):
        music_genre = _to_ko_genre(mood_summary.get("top_genre"))

    return {
        "top_category": youtube.get("top_category"),
        "music_genre": music_genre,
        "youtube_keyword": yt_keywords[0] if yt_keywords else None,
        "photo_keywords": photo_keywords[:3],
    }


# ── 진입점 ───────────────────────────────────────────────────────

def assemble_journal_input(
    user_id: int,
    target_date: date,
    db: Session,
    mood_summary: dict | None = None,
    recommended_articles: list[dict] | None = None,
) -> dict:
    """
    역할 A의 최종 구조화 JSON 산출물.
    recommender.run_recommendation() 끝에서 호출되어 analysis_result["structured"]로 실린다.
    """
    mood_summary = mood_summary or {}

    photo = build_photo_section(user_id, target_date, db)
    youtube = build_youtube_section(user_id, target_date, db)
    music = build_music_section(user_id, target_date, db, mood_summary)
    headline = build_headline(photo, youtube, music, mood_summary)

    return {
        "date": target_date.isoformat(),
        "photo": photo,
        "youtube": youtube,
        "music": music,
        "headline": headline,
        # 규칙#6: RSS+FAISS 추천 기사 결과를 구조화 JSON에 매단다.
        "recommended_articles": recommended_articles or [],
    }
