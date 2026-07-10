#!/bin/sh

# celery(자동 수집 스케줄러)는 Redis 장애 등으로 죽어도 이 루프가 자체적으로 재기동한다.
# 시연 트래픽을 받는 uvicorn을 celery/Redis 상태와 분리시켜, celery 쪽 문제가
# 라이브 API까지 끌어내리지 않게 한다.
(
  while true; do
    celery -A backend.tasks.celery_app worker -B --loglevel=info \
      --without-gossip --without-mingle --without-heartbeat
    echo "[start.sh] celery exited (rc=$?) — restarting in 5s"
    sleep 5
  done
) &
CELERY_SUPERVISOR_PID=$!

uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} &
UVICORN_PID=$!

# uvicorn이 죽으면 컨테이너 전체를 비정상 종료시켜 Fly의 on-failure 재시작 정책이 머신을 새로 띄우게 한다.
wait "$UVICORN_PID"
echo "[start.sh] uvicorn(pid=$UVICORN_PID) died — exiting so Fly restarts the machine"
kill "$CELERY_SUPERVISOR_PID" 2>/dev/null
exit 1
