#!/bin/sh
# Внешний сторож: если сайт не отвечает, сервер сам об этом не скажет — проверяем снаружи.
# Ставится в cron на сервере: */2 * * * * sh /opt/mystory/scripts/watchdog.sh
# Алерт — после двух неудачных проверок подряд, сообщение о восстановлении — когда сайт ожил.
set -u
DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV="$DIR/.env"
STATE="/var/tmp/mystory-watchdog.state"
URL="${WATCHDOG_URL:-https://mystorybook.site/health}"

TOKEN=$(grep -E '^TG_BOT_TOKEN=' "$ENV" | cut -d= -f2-)
CHATS=$(grep -E '^TG_ADMIN_CHAT_IDS=' "$ENV" | cut -d= -f2- | tr ',' ' ')
[ -n "$TOKEN" ] && [ -n "$CHATS" ] || exit 0

send() {
  for chat in $CHATS; do
    curl -s -m 15 "https://api.telegram.org/bot$TOKEN/sendMessage" \
      --data-urlencode "chat_id=$chat" --data-urlencode "text=$1" >/dev/null
  done
}

fails=$(cat "$STATE" 2>/dev/null || echo 0)
if curl -fsS -m 10 "$URL" >/dev/null 2>&1; then
  if [ "$fails" -ge 2 ]; then
    send "🟢 mystorybook.site снова отвечает"
  fi
  echo 0 > "$STATE"
else
  fails=$((fails + 1))
  echo "$fails" > "$STATE"
  if [ "$fails" -eq 2 ]; then
    status=$(docker inspect -f '{{.State.Status}} / {{if .State.Health}}{{.State.Health.Status}}{{end}}' mystory_api 2>/dev/null || echo "контейнер не найден")
    send "🔴 mystorybook.site не отвечает уже ~4 минуты. Контейнер: $status"
  fi
fi
