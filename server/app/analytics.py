"""Путь пользователя: какие события пишем и как вычисляем вехи интервью.

Ключевые шаги (создание книги, ответы, ИИ, фото, оплата) фиксирует сам сервер — их нельзя подделать.
Браузер присылает только события из белого списка: то, что видно лишь в интерфейсе.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# События, которые может прислать браузер (POST /api/event).
CLIENT_EVENTS = {
    "visit",          # открыл сайт (раз за сессию), с источником перехода
    "example_view",   # смотрел пример книги
    "offer_view",     # открыл предложение полной книги
    "buy_click",      # нажал «Оплатить»
    "checkout_view",  # открыл страницу оплаты с QR
    "paid_seen",      # увидел подтверждение оплаты
    "ai_style",       # включил «Литературный текст»
    "edit_open",      # открыл редактор книги
    "pdf_free",       # скачал PDF бесплатной книги
    "pdf_full",       # скачал PDF полной книги
    "recovery_copy",  # скопировал личную ссылку
}

# Воронка в админке — по порядку.
FUNNEL = [
    ("visit", "Зашли на сайт"),
    ("book_created", "Начали (первый ответ)"),
    ("free_finished", "Ответили на 12 бесплатных"),
    ("offer_view", "Открыли предложение"),
    ("buy_click", "Нажали «Оплатить»"),
    ("payment_created", "Получили счёт"),
    ("paid", "Оплатили"),
    ("full_started", "Начали полную книгу"),
    ("ai_chapter", "Собрали литературный текст"),
    ("pdf_full", "Скачали полный PDF"),
]

LABELS = {
    **dict(FUNNEL),
    "example_view": "Смотрел пример",
    "checkout_view": "Страница оплаты",
    "paid_seen": "Увидел подтверждение оплаты",
    "ai_style": "Включил литературный текст",
    "edit_open": "Открыл редактор",
    "pdf_free": "Скачал PDF (бесплатный)",
    "recovery_copy": "Скопировал личную ссылку",
    "full_finished": "Ответил на все вопросы",
    "ai_followup": "Получил уточняющие вопросы",
    "photo_added": "Добавил фото",
    "payment_failed": "Платёж не прошёл",
    "promo_visit": "Перешёл по промокоду",
    "link_rotated": "Выпустил новую личную ссылку",
    "recovered": "Открыл книгу по личной ссылке",
}

FREE_IDS = {f"f{i}" for i in range(1, 13)}


def answered_ids(data: dict[str, Any]) -> set[str]:
    answers = data.get("answers") or {}
    return {k for k, v in answers.items() if isinstance(v, dict) and str(v.get("text") or "").strip()}


def milestones(before: dict[str, Any], after: dict[str, Any], full_total: int) -> list[str]:
    """Вехи, которых человек достиг этим сохранением."""
    old, new = answered_ids(before), answered_ids(after)
    reached = []
    if len(new & FREE_IDS) == len(FREE_IDS) and len(old & FREE_IDS) < len(FREE_IDS):
        reached.append("free_finished")
    old_full, new_full = old - FREE_IDS, new - FREE_IDS
    if new_full and not old_full:
        reached.append("full_started")
    if full_total and len(new_full) >= full_total > len(old_full):
        reached.append("full_finished")
    return reached


def visit_source(meta: dict[str, Any], own_host: str) -> str:
    """Откуда пришёл посетитель: utm_source, домен реферера или прямой заход."""
    utm = str(meta.get("utm_source") or "").strip().lower()
    if utm:
        return re.sub(r"[^a-z0-9_.-]", "", utm)[:40] or "utm"
    ref = urlparse(str(meta.get("ref") or ""))
    host = (ref.hostname or "").removeprefix("www.")
    if not host or host == own_host.removeprefix("www."):
        return "прямой заход"
    for name, needle in (("yandex", "yandex."), ("google", "google."), ("telegram", "t.me"), ("vk", "vk.com"), ("instagram", "instagram.")):
        if needle in host:
            return name
    return host[:60]


def clean_meta(raw: Any) -> dict[str, str]:
    """Только короткие строковые поля — никакого произвольного содержимого."""
    if not isinstance(raw, dict):
        return {}
    allowed = ("ref", "utm_source", "utm_medium", "utm_campaign", "path", "chapter")
    return {k: str(raw[k])[:200] for k in allowed if raw.get(k)}
