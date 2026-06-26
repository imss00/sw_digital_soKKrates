import re
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.browsing_history import BrowsingHistory
from backend.models.youtube_history import YouTubeHistory

router = APIRouter()


class BrowsingRecord(BaseModel):
    url: str
    domain: str | None = None
    title: str | None = None
    article_text: str | None = None
    is_article: bool = False
    visited_at: datetime
    time_spent_sec: int | None = None
    visit_count: int = 1


class BrowsingBatch(BaseModel):
    records: list[BrowsingRecord]


@router.post("/batch")
def receive_browsing_batch(batch: BrowsingBatch, user_id: int = 3, db: Session = Depends(get_db)):
    """Chrome Extension에서 배치로 전송받는 엔드포인트"""
    inserted = 0
    for record in batch.records:
        entry = BrowsingHistory(
            user_id=user_id,
            url=record.url,
            domain=record.domain,
            title=record.title,
            article_text=record.article_text[:5000] if record.article_text else None,
            is_article=record.is_article,
            visited_at=record.visited_at,
            time_spent_sec=record.time_spent_sec,
            visit_count=record.visit_count,
        )
        db.add(entry)
        inserted += 1

    db.commit()
    return {"inserted": inserted}


@router.post("/youtube-detect")
def receive_youtube_detect(batch: BrowsingBatch, user_id: int = 3, db: Session = Depends(get_db)):
    """Chrome Extension에서 감지한 YouTube 시청 기록 수신"""
    inserted = 0
    new_video_ids = []

    for record in batch.records:
        match = re.search(r"v=([a-zA-Z0-9_-]{11})", record.url)
        if not match:
            continue

        video_id = match.group(1)
        existing = (
            db.query(YouTubeHistory)
            .filter_by(user_id=user_id, video_id=video_id, watched_at=record.visited_at)
            .first()
        )
        if existing:
            continue

        db.add(YouTubeHistory(
            user_id=user_id,
            video_id=video_id,
            title=record.title,
            watched_at=record.visited_at,
            source="extension",
        ))
        new_video_ids.append(video_id)
        inserted += 1

    db.commit()

    if new_video_ids and settings.google_api_key:
        from backend.collectors.youtube_enricher import enrich_and_update
        enrich_and_update(list(set(new_video_ids)), user_id=user_id, db=db, api_key=settings.google_api_key)

    return {"inserted": inserted}
