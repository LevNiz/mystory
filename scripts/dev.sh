#!/bin/sh
# Локальный запуск сервера с ключами из .env (cookie без Secure, адрес localhost).
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export COOKIE_SECURE=0 PUBLIC_URL=http://localhost:8000 DB_PATH=./data/dev.db WEB_DIR=./web
exec "${PYTHON:-python3}" -m uvicorn server.app.main:app --port 8000 --reload --reload-dir server --reload-dir web
