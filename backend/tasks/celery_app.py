from celery import Celery
from celery.schedules import crontab

from backend.config import settings

celery_app = Celery("paperback", broker=settings.redis_url)

celery_app.conf.update(
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
