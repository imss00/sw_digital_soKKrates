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


def default_target_date() -> date:
    """다른 모듈(예: 자동 인쇄 파이프라인)에서 쓰는 공개 진입점. _default_target_date의 별칭."""
    return _default_target_date()


def _calendar_collection_dates(target_date: date) -> list[date]:
    """저널 회고일과 저널에 표시할 다음날 일정을 함께 수집한다."""
    return [target_date, target_date + timedelta(days=1)]


def _log_results(task_name: str, results: dict) -> None:
    errors = {uid: r for uid, r in results.items() if r.get("status") == "error"}
    if errors:
        logger.warning("%s: %d/%d users errored -> %s", task_name, len(errors), len(results), errors)
    else:
        logger.info("%s: %d users processed -> %s", task_name, len(results), results)


@celery_app.task(name="backend.tasks.collection_tasks.collect_daily")
def collect_daily():
    """자정 30분: Google Calendar 수집 (Google token 있는 모든 유저)."""
    db = SessionLocal()
    try:
        from backend.collectors.calendar_collector import collect_calendar
        from backend.models.user import User

        users = db.query(User).filter(User.google_refresh_token.isnot(None)).all()
        target_dates = _calendar_collection_dates(_default_target_date())
        results = {}
        for user in users:
            for target_date in target_dates:
                results[f"{user.id}:{target_date}"] = collect_calendar(
                    user_id=user.id,
                    db=db,
                    target_date=target_date,
                )
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


# 매 실행마다 되돌아보며 재확인할 일수.
# 크롬 익스텐션이 방문기록을 며칠 늦게/몰아서 sync해도, normalize_daily가
# idempotent(user+source+source_id 중복 skip)라 이 창 안이면 다음 실행 때 자동으로 주워담는다.
NORMALIZE_BACKFILL_DAYS = 7


@celery_app.task(name="backend.tasks.collection_tasks.normalize_and_trigger")
def normalize_and_trigger():
    """새벽 1시: 정규화 + Phase 2 트리거 (모든 유저).

    '어제 하루'만 한 번 보고 지나가면, 그 시점에 아직 도착하지 않은 원본은
    영영 정규화되지 못한다. 그래서 최근 NORMALIZE_BACKFILL_DAYS일을 매번 재확인하고,
    이번 실행에서 실제로 새 문서가 삽입된 (user, date)에 대해서만 Phase 2를 돌린다.
    (이미 정규화된 날짜는 전부 중복 skip → Phase 2도 재실행하지 않는다.)
    """
    db = SessionLocal()
    try:
        from backend.normalizer.normalize import normalize_daily
        from backend.models.user import User
        from backend.tasks.analysis_tasks import record_journal_run, run_phase2

        latest_date = _default_target_date()  # KST 기준 어제
        target_dates = [latest_date - timedelta(days=i) for i in range(NORMALIZE_BACKFILL_DAYS)]
        users = db.query(User).all()

        results = {}
        pending_phase2 = []  # 이번에 새로 정규화된 (user_id, date)만 Phase 2 대상
        for user in users:
            for target_date in target_dates:
                res = normalize_daily(user_id=user.id, target_date=target_date, db=db)
                results[f"{user.id}:{target_date}"] = res
                if res.get("inserted", 0) > 0:
                    pending_phase2.append((user.id, target_date))

        queued = {}
        for uid, target_date in pending_phase2:
            task = run_phase2.delay(user_id=uid, target_date_str=str(target_date))
            queued[f"{uid}:{target_date}"] = task.id
            record_journal_run(
                db,
                user_id=uid,
                target_date=target_date,
                status="queued",
                stage="queued",
                celery_task_id=task.id,
            )

        _log_results("normalize_and_trigger", results)
        return {"latest_date": str(latest_date), "normalize": results, "queued": queued}
    finally:
        db.close()
