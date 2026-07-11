from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.journal import Journal
from backend.models.photo import Photo
from backend.routers.auth import decode_jwt

router = APIRouter()
KST = timezone(timedelta(hours=9))


def _resolve_user_id(authorization: str | None) -> int:
    """저널은 실제 로그인 JWT가 있어야만 볼 수 있다."""
    if authorization and authorization.startswith("Bearer "):
        return decode_jwt(authorization.removeprefix("Bearer "))
    raise HTTPException(status_code=401, detail="인증 필요: Authorization 헤더가 필요합니다")


@router.get("/{target_date}")
def get_journal(
    target_date: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """완성된 저널 조회. 프론트엔드/프린터가 저널을 가져오는 유일한 경로.

    target_date는 저널이 다루는 날짜(YYYY-MM-DD, journal_composer의 target_date 기준 — "어제").
    """
    resolved_user_id = _resolve_user_id(authorization)
    parsed = date.fromisoformat(target_date)
    journal = (
        db.query(Journal)
        .filter(Journal.user_id == resolved_user_id, Journal.target_date == parsed)
        .first()
    )
    if journal is None:
        raise HTTPException(status_code=404, detail="Journal not found for this user/date")

    data = journal.to_dict()
    day_start = datetime.combine(parsed, datetime.min.time(), tzinfo=KST)
    day_end = day_start + timedelta(days=1)
    photo = (
        db.query(Photo)
        .filter(
            Photo.user_id == resolved_user_id,
            Photo.taken_at >= day_start,
            Photo.taken_at < day_end,
            Photo.image_data.isnot(None),
        )
        .order_by(func.random())
        .first()
    )
    if photo:
        data["photo"] = {
            "id": photo.id,
            "url": f"/photos/{photo.id}/content",
            "filename": photo.original_filename,
            "taken_at": photo.taken_at.isoformat() if photo.taken_at else None,
        }
    else:
        data["photo"] = None

    return data
