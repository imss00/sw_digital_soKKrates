import logging
from datetime import date, datetime, timedelta, timezone

from backend.tasks.celery_app import celery_app
from backend.database import SessionLocal

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))


def _default_target_date() -> date:
    """자동 저널은 KST 기준 어제를 대상으로 한다.

    Fly 컨테이너의 시스템 timezone이 UTC여도 Celery beat는 Asia/Seoul로 돈다.
    여기서 date.today()를 쓰면 새벽 1시 KST에 UTC 기준 날짜가 아직 전날이라
    target_date가 하루 더 밀릴 수 있으므로 명시적으로 KST now를 사용한다.
    """
    return datetime.now(KST).date() - timedelta(days=1)


def _log_results(task_name: str, results: dict) -> None:
    errors = {uid: r for uid, r in results.items() if r.get("status") == "error"}
    if errors:
        logger.warning("%s: %d/%d users errored -> %s", task_name, len(errors), len(results), errors)
    else:
        logger.info("%s: %d users processed -> %s", task_name, len(results), results)


@celery_app.task(name="backend.tasks.collection_tasks.collect_daily")
def collect_daily():
    """자정 30분: Google Calendar 수집 (Google token 있는 모든 유저)"""
    db = SessionLocal()
    try:
        from backend.collectors.calendar_collector import collect_calendar
        from backend.models.user import User

        users = db.query(User).filter(User.google_refresh_token.isnot(None)).all()
        results = {}
        for user in users:
            results[user.id] = collect_calendar(user_id=user.id, db=db)
        _log_results("collect_daily", results)
        return results
    finally:
        db.close()


@celery_app.task(name="backend.tasks.collection_tasks.collect_spotify_task")
def collect_spotify_task():
    """4시간마다: Spotify 폴링 (Spotify token 있는 모든 유저)"""
    db = SessionLocal()
    try:
        from backend.collectors.spotify_collector import collect_spotify
        from backend.models.user import User

        users = db.query(User).filter(User.spotify_refresh_token.isnot(None)).all()
        results = {}
        for user in users:
            results[user.id] = collect_spotify(user_id=user.id, db=db)
        _log_results("collect_spotify_task", results)
        return results
    finally:
        db.close()


@celery_app.task(name="backend.tasks.collection_tasks.normalize_and_trigger")
def normalize_and_trigger():
    """새벽 1시: 정규화 + Phase 2 트리거 (모든 유저)"""
    db = SessionLocal()
    try:
        from backend.normalizer.normalize import normalize_daily
        from backend.models.user import User
        from backend.tasks.analysis_tasks import record_journal_run, run_phase2

        target_date = _default_target_date()
        users = db.query(User).all()
        results = {}
        for user in users:
            results[user.id] = normalize_daily(user_id=user.id, target_date=target_date, db=db)

        queued = {}
        for uid in results:
            task = run_phase2.delay(user_id=uid, target_date_str=str(target_date))
            queued[uid] = task.id
            record_journal_run(
                db,
                user_id=uid,
                target_date=target_date,
                status="queued",
                stage="queued",
                celery_task_id=task.id,
            )

        _log_results("normalize_and_trigger", results)
        return {"target_date": str(target_date), "normalize": results, "queued": queued}
    finally:
        db.close()
