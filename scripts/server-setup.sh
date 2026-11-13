#!/bin/sh
# Первичная настройка чистого сервера (Ubuntu/Debian): Docker, файрвол, код, сторож в cron.
# Запуск с локальной машины: sh scripts/server-setup.sh   (нужен SSH-ключ к серверу)
# .env и база переносятся отдельно (scp), сертификат — scripts/issue-cert.sh.
set -e
HOST="${DEPLOY_HOST:-root@144.124.229.127}"
ssh "$HOST" 'set -e
  export DEBIAN_FRONTEND=noninteractive
  if ! command -v docker >/dev/null; then
    apt-get update -q && apt-get install -yq ca-certificates curl git
    curl -fsSL https://get.docker.com | sh
  fi
  command -v git >/dev/null || { apt-get update -q && apt-get install -yq git; }
  if command -v ufw >/dev/null; then
    ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw --force enable >/dev/null
  fi
  [ -d /opt/mystory/.git ] || git clone --quiet https://github.com/LevNiz/mystory.git /opt/mystory
  CRON="*/2 * * * * sh /opt/mystory/scripts/watchdog.sh"
  ( crontab -l 2>/dev/null | grep -v mystory/scripts/watchdog.sh; echo "$CRON" ) | crontab -
  docker --version; docker compose version'
