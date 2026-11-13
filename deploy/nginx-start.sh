#!/bin/sh
# Запуск nginx: есть сертификат — полный конфиг, нет — только HTTP для его выпуска.
# Раз в 6 часов перечитываем конфиг, чтобы подхватить продлённый сертификат.
set -e
CERT=/etc/letsencrypt/live/mystorybook.site/fullchain.pem
pick() {
  if [ -f "$CERT" ]; then cp /etc/mystory/nginx.conf /etc/nginx/conf.d/default.conf
  else cp /etc/mystory/nginx-http.conf /etc/nginx/conf.d/default.conf; fi
}
pick
( while :; do sleep 21600; pick; nginx -s reload; done ) &
exec nginx -g 'daemon off;'
