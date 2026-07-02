#!/bin/sh

celery -A backend.tasks.celery_app worker -B --loglevel=info &
CELERY_PID=$!

uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} &
UVICORN_PID=$!

# celery(자동 수집 스케줄러) 또는 uvicorn 중 하나라도 죽으면
# Fly 헬스체크(uvicorn /health)만으로는 감지가 안 되므로,
# 컨테이너 전체를 비정상 종료시켜 Fly의 on-failure 재시작 정책이 머신을 새로 띄우게 한다.
while kill -0 "$CELERY_PID" 2>/dev/null && kill -0 "$UVICORN_PID" 2>/dev/null; do
  sleep 5
done

echo "[start.sh] celery(pid=$CELERY_PID) or uvicorn(pid=$UVICORN_PID) died — exiting so Fly restarts the machine"
kill "$CELERY_PID" "$UVICORN_PID" 2>/dev/null
exit 1
