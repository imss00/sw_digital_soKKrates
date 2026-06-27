from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db

router = APIRouter()


def _verify_secret(x_webhook_secret: str | None = Header(None)):
    if settings.webhook_secret and x_webhook_secret != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Webhook-Secret header")


@router.post("/collect/spotify")
def trigger_spotify(
    user_id: int = 1,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_secret),
):
    from backend.collectors.spotify_collector import collect_spotify
    return collect_spotify(user_id=user_id, db=db)


@router.post("/collect/calendar")
def trigger_calendar(
    user_id: int = 1,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_secret),
):
    from backend.collectors.calendar_collector import collect_calendar
    return collect_calendar(user_id=user_id, db=db)


@router.post("/collect/notion")
def trigger_notion(
    user_id: int = 1,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_secret),
):
    from backend.collectors.notion_collector import collect_notion
    return collect_notion(user_id=user_id, db=db)


@router.post("/normalize")
def trigger_normalize(
    user_id: int = 1,
    target_date: str | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_secret),
):
    from backend.normalizer.normalize import normalize_daily
    from datetime import date
    parsed = date.fromisoformat(target_date) if target_date else date.today()
    return normalize_daily(user_id=user_id, target_date=parsed, db=db)
