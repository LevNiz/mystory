#!/bin/sh
# Обновляет ?v=… у CSS/JS в web/*.html, чтобы браузеры не держали старые файлы после деплоя.
v=$(date +%Y%m%d%H%M%S)
for f in "$(dirname "$0")"/../web/*.html; do
  sed -i '' -E "s/\?v=[A-Za-z0-9_]+/?v=$v/g" "$f" 2>/dev/null || sed -i -E "s/\?v=[A-Za-z0-9_]+/?v=$v/g" "$f"
done
echo "v=$v"
