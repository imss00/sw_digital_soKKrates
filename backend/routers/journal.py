from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.journal import Journal
from backend.routers.auth import decode_jwt

router = APIRouter()


def _resolve_user_id(authorization: str | None, query_user_id: int | None) -> int:
    """browsing.py와 동일한 규칙: Authorization 헤더(JWT)가 있으면 그걸 우선하고,
    없으면 명시적으로 넘어온 user_id로 폴백한다. 둘 다 없으면 401."""
    if authorization and authorization.startswith("Bearer "):
        return decode_jwt(authorization.removeprefix("Bearer "))
    if query_user_id is not None:
        return query_user_id
    raise HTTPException(status_code=401, detail="인증 필요: Authorization 헤더 또는 user_id 필요")


@router.get("/{target_date}")
def get_journal(
    target_date: str,
    user_id: int | None = None,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """완성된 저널 조회. 프론트엔드/프린터가 저널을 가져오는 유일한 경로.

    target_date는 저널이 다루는 날짜(YYYY-MM-DD, journal_composer의 target_date 기준 — "어제").
    """
    resolved_user_id = _resolve_user_id(authorization, user_id)
    parsed = date.fromisoformat(target_date)
    journal = (
        db.query(Journal)
        .filter(Journal.user_id == resolved_user_id, Journal.target_date == parsed)
        .first()
    )
    if journal is None:
        raise HTTPException(status_code=404, detail="Journal not found for this user/date")

    return journal.to_dict()
