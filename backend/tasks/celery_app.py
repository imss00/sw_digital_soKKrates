from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from backend.config import settings

celery_app = Celery("paperback", broker=settings.redis_url)


@worker_process_init.connect
def _dispose_engine_after_fork(**kwargs):
    """prefork 워커가 fork 시 부모의 DB 커넥션(소켓)을 그대로 물려받아 공유하는 걸 막기 위해,
    자식 프로세스가 뜨자마자 상속받은 커넥션을 버리고 새로 열게 한다."""
    from backend.database import engine

    engine.dispose()

celery_app.conf.update(
    imports=("backend.tasks.collection_tasks", "backend.tasks.analysis_tasks"),
    timezone="Asia/Seoul",
    enable_utc=False,
    beat_schedule={
        "daily-collection": {
            "task": "backend.tasks.collection_tasks.collect_daily",
            "schedule": crontab(hour=0, minute=30),
        },
        "daily-normalization": {
            "task": "backend.tasks.collection_tasks.normalize_and_trigger",
            "schedule": crontab(hour=1, minute=0),
        },
        "spotify-polling": {
            "task": "backend.tasks.collection_tasks.collect_spotify_task",
            "schedule": crontab(minute=0, hour="*/4"),
        },
    },
)
