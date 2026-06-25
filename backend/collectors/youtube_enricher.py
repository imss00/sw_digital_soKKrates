import re

from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from backend.models.youtube_history import YouTubeHistory


def _parse_duration(duration: str) -> int | None:
    """ISO 8601 duration (PT5M30S) → 초"""
    if not duration:
        return None
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return None
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    return h * 3600 + m * 60 + s


def fetch_youtube_details(video_ids: list[str], api_key: str) -> dict:
    """YouTube Data API v3로 영상 메타데이터 조회 (무료, 1건 = 1유닛)"""
    if not video_ids or not api_key:
        return {}

    youtube = build("youtube", "v3", developerKey=api_key)
    result = {}

    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        try:
            resp = youtube.videos().list(
                part="snippet,contentDetails",
                id=",".join(batch),
            ).execute()
        except Exception:
            continue

        for item in resp.get("items", []):
            vid = item["id"]
            snippet = item.get("snippet", {})
            details = item.get("contentDetails", {})
            tags = snippet.get("tags") or []

            result[vid] = {
                "title": snippet.get("title"),
                "description": (snippet.get("description") or "")[:500],
                "channel_name": snippet.get("channelTitle"),
                "channel_id": snippet.get("channelId"),
                "category_id": int(snippet["categoryId"]) if snippet.get("categoryId") else None,
                "tags": tags[:10],
                "duration_sec": _parse_duration(details.get("duration", "")),
            }

    return result


def enrich_and_update(video_ids: list[str], user_id: int, db: Session, api_key: str) -> int:
    """API로 가져온 메타데이터를 youtube_history 레코드에 덮어씀"""
    details = fetch_youtube_details(video_ids, api_key)
    if not details:
        return 0

    updated = 0
    for video_id, data in details.items():
        records = (
            db.query(YouTubeHistory)
            .filter_by(user_id=user_id, video_id=video_id)
            .all()
        )
        for r in records:
            r.title = data["title"] or r.title
            r.description = data["description"] or None
            r.channel_name = data["channel_name"] or r.channel_name
            r.channel_id = data["channel_id"]
            r.category_id = data["category_id"]
            r.tags = data["tags"] or None
            r.duration_sec = data["duration_sec"]
            updated += 1

    db.commit()
    return updated
