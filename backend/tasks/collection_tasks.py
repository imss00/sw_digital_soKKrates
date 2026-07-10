import logging
from datetime import date, timedelta

from backend.tasks.celery_app import celery_app
from backend.database import SessionLocal

logger = logging.getLogger(__name__)


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

        target_date = date.today() - timedelta(days=1)
        users = db.query(User).all()
        results = {}
        for user in users:
            results[user.id] = normalize_daily(user_id=user.id, target_date=target_date, db=db)

        from backend.tasks.analysis_tasks import run_phase2
        for uid in results:
            run_phase2.delay(user_id=uid, target_date_str=str(target_date))

        return results
    finally:
        db.close()
