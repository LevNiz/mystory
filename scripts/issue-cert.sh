#!/bin/sh
# Выпуск сертификата Let's Encrypt. Запускать, когда DNS домена уже указывает на сервер.
# Запуск с локальной машины: sh scripts/issue-cert.sh
set -e
HOST="${DEPLOY_HOST:-root@144.124.229.127}"
ssh "$HOST" 'set -e
  cd /opt/mystory
  docker compose run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot \
    -d mystorybook.site -d www.mystorybook.site \
    --register-unsafely-without-email --agree-tos --non-interactive
  docker compose restart nginx
  echo "сертификат выпущен, nginx перезапущен с HTTPS"'
