import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.youtube_history import YouTubeHistory

router = APIRouter()


def extract_video_id(url: str) -> str | None:
    match = re.search(r"v=([a-zA-Z0-9_-]{11})", url)
    return match.group(1) if match else None


@router.post("/takeout")
async def upload_takeout(file: UploadFile = File(...), user_id: int = 3, db: Session = Depends(get_db)):
    """Google Takeout watch-history.json 업로드 + 파싱"""
    content = await file.read()
    data = json.loads(content)

    inserted = 0
    new_video_ids = []

    for entry in data:
        title = entry.get("title", "")
        if title.startswith("Watched "):
            title = title[8:]

        title_url = entry.get("titleUrl", "")
        video_id = extract_video_id(title_url)
        if not video_id:
            continue

        watched_at_str = entry.get("time", "")
        try:
            watched_at = datetime.fromisoformat(watched_at_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        channel_name = None
        subtitles = entry.get("subtitles", [])
        if subtitles:
            channel_name = subtitles[0].get("name")

        existing = (
            db.query(YouTubeHistory)
            .filter_by(user_id=user_id, video_id=video_id, watched_at=watched_at)
            .first()
        )
        if existing:
            continue

        db.add(YouTubeHistory(
            user_id=user_id,
            video_id=video_id,
            title=title,
            channel_name=channel_name,
            watched_at=watched_at,
            source="takeout",
        ))
        new_video_ids.append(video_id)
        inserted += 1

    db.commit()

    if new_video_ids and settings.google_api_key:
        from backend.collectors.youtube_enricher import enrich_and_update
        enriched = enrich_and_update(list(set(new_video_ids)), user_id=user_id, db=db, api_key=settings.google_api_key)
    else:
        enriched = 0

    return {"inserted": inserted, "enriched": enriched, "total_entries": len(data)}
