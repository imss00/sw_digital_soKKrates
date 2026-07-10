from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.journal import Journal
from backend.routers.auth import decode_jwt

router = APIRouter()


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

    return journal.to_dict()
