from datetime import date, timedelta

from backend.tasks.celery_app import celery_app
from backend.database import SessionLocal


@celery_app.task(name="backend.tasks.collection_tasks.collect_daily")
def collect_daily():
    """자정 30분: Calendar 수집 (Notion은 OAuth 심사 대기 중, 추후 추가)"""
    db = SessionLocal()
    try:
        from backend.collectors.calendar_collector import collect_calendar

        cal_result = collect_calendar(user_id=1, db=db)

        return {
            "calendar": cal_result,
        }
    finally:
        db.close()


@celery_app.task(name="backend.tasks.collection_tasks.collect_spotify_task")
def collect_spotify_task():
    """4시간마다: Spotify 폴링"""
    db = SessionLocal()
    try:
        from backend.collectors.spotify_collector import collect_spotify
        return collect_spotify(user_id=1, db=db)
    finally:
        db.close()


@celery_app.task(name="backend.tasks.collection_tasks.normalize_and_trigger")
def normalize_and_trigger():
    """새벽 1시: 정규화 + Phase 2 트리거"""
    db = SessionLocal()
    try:
        from backend.normalizer.normalize import normalize_daily
        result = normalize_daily(user_id=1, target_date=date.today() - timedelta(days=1), db=db)

        # TODO: Phase 2 분석 파이프라인 호출
        # from backend.tasks.analysis_tasks import run_analysis
        # run_analysis.delay(user_id=1, target_date=str(date.today()))

        return result
    finally:
        db.close()
