from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db

router = APIRouter()


@router.post("/collect/spotify")
def trigger_spotify(db: Session = Depends(get_db)):
    """Spotify 수집 수동 트리거 (디버깅용)"""
    from backend.collectors.spotify_collector import collect_spotify
    result = collect_spotify(user_id=1, db=db)
    return result


@router.post("/collect/calendar")
def trigger_calendar(db: Session = Depends(get_db)):
    """Calendar 수집 수동 트리거"""
    from backend.collectors.calendar_collector import collect_calendar
    result = collect_calendar(user_id=1, db=db)
    return result


@router.post("/collect/notion")
def trigger_notion(db: Session = Depends(get_db)):
    """Notion 수집 수동 트리거"""
    from backend.collectors.notion_collector import collect_notion
    result = collect_notion(user_id=1, db=db)
    return result


@router.post("/normalize")
def trigger_normalize(db: Session = Depends(get_db)):
    """정규화 수동 트리거"""
    from backend.normalizer.normalize import normalize_daily
    from datetime import date
    result = normalize_daily(user_id=1, target_date=date.today(), db=db)
    return result
