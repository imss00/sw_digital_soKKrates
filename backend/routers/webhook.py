from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db

router = APIRouter()


@router.post("/collect/spotify")
def trigger_spotify(user_id: int = 1, db: Session = Depends(get_db)):
    """Spotify 수집 수동 트리거 (디버깅용)"""
    from backend.collectors.spotify_collector import collect_spotify
    result = collect_spotify(user_id=user_id, db=db)
    return result


@router.post("/collect/calendar")
def trigger_calendar(user_id: int = 1, db: Session = Depends(get_db)):
    """Calendar 수집 수동 트리거"""
    from backend.collectors.calendar_collector import collect_calendar
    result = collect_calendar(user_id=user_id, db=db)
    return result


@router.post("/collect/notion")
def trigger_notion(user_id: int = 1, db: Session = Depends(get_db)):
    """Notion 수집 수동 트리거"""
    from backend.collectors.notion_collector import collect_notion
    result = collect_notion(user_id=user_id, db=db)
    return result


@router.post("/normalize")
def trigger_normalize(user_id: int = 1, db: Session = Depends(get_db)):
    """정규화 수동 트리거"""
    from backend.normalizer.normalize import normalize_daily
    from datetime import date
    result = normalize_daily(user_id=user_id, target_date=date.today(), db=db)
    return result
