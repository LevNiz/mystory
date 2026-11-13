#!/bin/sh
# Деплой на сервер: подтягивает main из GitHub, пересобирает контейнер, ждёт /health.
# Запуск с локальной машины: sh scripts/deploy.sh   (нужен SSH-ключ к серверу)
set -e
HOST="${DEPLOY_HOST:-root@144.124.229.127}"
ssh "$HOST" 'set -e
  cd /opt/mystory
  git fetch --quiet origin main
  git reset --hard --quiet origin/main
  # Подойдёт и плагин `docker compose`, и старый docker-compose 1.29.
  if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC=docker-compose; fi
  $DC build api
  # docker-compose 1.29 падает с KeyError ContainerConfig при пересоздании — удаляем контейнер явно (простой ~5 с).
  $DC rm -s -f api
  $DC up -d
  for i in $(seq 1 30); do
    if docker exec mystory_api python -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8000/health\", timeout=2)" 2>/dev/null; then
      echo "mystory: healthy"; docker image prune -f >/dev/null; exit 0
    fi
    sleep 2
  done
  echo "mystory: health check failed" >&2; docker logs --tail 50 mystory_api >&2; exit 1'
