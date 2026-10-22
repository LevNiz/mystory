#!/bin/sh
# Обновляет ?v=… у CSS/JS в index.html, чтобы браузеры не держали старые файлы после деплоя.
v=$(date +%Y%m%d%H%M%S)
sed -i '' -E "s/\?v=[A-Za-z0-9_]+/?v=$v/g" "$(dirname "$0")/index.html"
echo "v=$v"
