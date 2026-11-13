# Книга моей жизни — mystorybook.site

**Интервью с самим собой.** Человек отвечает на вопросы голосом или текстом и получает автобиографию в PDF. Бесплатно — 12 вопросов, полная книга (13 глав, 116 вопросов) — 1 490 ₽ единоразово.

## Устройство

```
web/        фронтенд (статический, без сборки): index.html, css/, js/, 404, оферта, политика, robots, sitemap
server/     FastAPI: синхронизация книги, ИИ, оплата, раздача статики
deploy/     nginx (HTTPS) для docker-compose
scripts/    деплой, пререндер лендинга, версии ассетов, локальный запуск
```

- **Хранение.** Книга лежит на сервере (SQLite в docker-томе `mystory_data`). Браузер получает случайный токен в httpOnly-cookie; в базе — только его хэш. Для продолжения на другом устройстве есть личная ссылка `/r/<токен>`.
- **ИИ** (OpenAI-совместимый API apibost, ключи как у wgpt_bot): уточняющие вопросы по ответу (`/api/ai/followup`) и литературный текст главы (`/api/ai/chapter`). Промпт запрещает добавлять факты. Текст собирается только из ответов, сохранённых на сервере. Лимиты: на книгу в сутки, на IP в час, общий семафор параллельных запросов, плюс лимиты nginx.
- **Оплата**: переходим на Lava. Пока она не подключена, `/api/pay` отвечает 503, а экран оплаты показывает заглушку. Статус оплаты знает только сервер: подтверждать будем запросом в API провайдера, а не по телу уведомления.
- **Безопасность.** Секреты только в `.env` на сервере. CSP, HSTS, X-Frame-Options, защита от CSRF (заголовок `X-Requested-With`), ограничения размера тел.
- **SEO.** Лендинг пререндерен в `web/index.html` (`node scripts/prerender.mjs`), canonical, Open Graph, JSON-LD (WebSite, Product, FAQPage), robots.txt, sitemap.xml, настоящий 404.

Вопросы — в `web/js/questions.js` (JSON, его же читает сервер). Шаблоны `{был|была}` подставляют форму по полу автора.

## Аналитика

Яндекс Метрика — в `web/js/analytics.js`: впиши номер счётчика в `METRIKA_ID`. Цели («JavaScript-событие»): `free_finished`, `offer_view`, `buy_click`. Вебвизор выключен.

## Локально

```bash
cp .env.example .env   # заполнить ключи
python3 -m venv .venv && .venv/bin/pip install -r server/requirements.txt
PYTHON=.venv/bin/python sh scripts/dev.sh   # http://localhost:8000
```

## Сервер

Отдельный сервер, всё в `docker-compose.yml`: `mystory_api`, `mystory_nginx` (HTTPS, `deploy/nginx.conf`) и `mystory_certbot` (продление сертификата). Чистый сервер готовит `scripts/server-setup.sh`, сертификат выпускает `scripts/issue-cert.sh` (когда DNS уже смотрит на сервер). Внешний сторож `scripts/watchdog.sh` стоит в cron.

Перед коммитом: `sh scripts/bump-version.sh` (сброс кэша CSS/JS) и, если менялся лендинг, `node scripts/prerender.mjs`. Деплой: `sh scripts/deploy.sh`.

## Дальше

- Заполнить реквизиты в `web/terms.html` и `web/privacy.html` (помечены жёлтым).
- Номер счётчика Метрики.
- Резервные копии базы (`mystory_data`).
