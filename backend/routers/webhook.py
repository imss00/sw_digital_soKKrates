import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db

router = APIRouter()


def _verify_secret(x_webhook_secret: str | None = Header(None)):
    if not settings.webhook_secret:
        if settings.allow_unprotected_webhooks:
            return
        raise HTTPException(
            status_code=503,
            detail="WEBHOOK_SECRET is required before webhook endpoints can be used",
        )
    if not x_webhook_secret or not hmac.compare_digest(x_webhook_secret, settings.webhook_secret):
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


@router.post("/generate-journal")
def trigger_generate_journal(
    user_id: int = 1,
    target_date: str | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_secret),
):
    """정규화를 즉시 실행하고, Phase 2-3(임베딩~저널생성)은 celery 큐에 넣어 비동기로 처리.

    새벽 자동 스케줄을 기다리지 않고 시연 중 바로 저널을 생성할 때 사용.
    target_date를 생략하면 다른 파이프라인(nightly job)과 동일하게 "어제"를 기준으로 삼는다 —
    journal_composer가 target_date를 어제로 해석해 target_date+1(오늘)의 캘린더 일정을 읽어오므로,
    여기서 오늘 날짜를 기본값으로 쓰면 "오늘 일정" 지면에 내일 일정이 뜨는 어긋남이 생긴다.

    Phase 2-3(임베딩+RSS수집+여러 번의 LLM 호출)은 수 분이 걸릴 수 있어 요청 안에서 동기 실행하면
    Fly.io 프록시/클라이언트 타임아웃 위험이 있다. 그래서 정규화만 즉시 실행해 결과를 바로 보여주고,
    Phase 2-3는 기존 celery task(run_phase2)에 위임한 뒤 즉시 응답한다.
    완료 여부는 GET /journal/{target_date}로 폴링해서 확인하면 된다(완료 전엔 404).
    """
    from datetime import date, timedelta
    from backend.normalizer.normalize import normalize_daily
    from backend.tasks.analysis_tasks import run_phase2

    parsed = date.fromisoformat(target_date) if target_date else date.today() - timedelta(days=1)
    normalize_result = normalize_daily(user_id=user_id, target_date=parsed, db=db)
    task = run_phase2.delay(user_id=user_id, target_date_str=parsed.isoformat())
    return {
        "normalize": normalize_result,
        "phase2": {"status": "queued", "task_id": task.id},
        "poll": f"/journal/{parsed.isoformat()}?user_id={user_id}",
    }
