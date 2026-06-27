#!/bin/sh
celery -A backend.tasks.celery_app worker -B --loglevel=info &
uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
