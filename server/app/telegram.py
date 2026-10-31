"""Уведомления админу в Telegram: сбои, оплаты, сводка за день и ежедневный бэкап базы.

Подписаться может только тот, кто знает секретный код: https://t.me/<бот>?start=<TG_LINK_CODE>.
Бэкап содержит личные истории пользователей, поэтому бот никому другому ничего не шлёт.
"""

from __future__ import annotations

import asyncio
import gzip
import html
import json
import logging
import time
from typing import Any

import httpx

log = logging.getLogger("mystory.telegram")

API = "https://api.telegram.org/bot{token}/{method}"
MAX_DOCUMENT = 49 * 1024 * 1024  # лимит Telegram для ботов — 50 МБ


class Telegram:
    def __init__(self, token: str, db: Any, env_chats: frozenset[str], link_code: str) -> None:
        self._token = token
        self._db = db
        self._env_chats = env_chats
        self._link_code = link_code
        self._http = httpx.AsyncClient(timeout=30)
        self._offset = 0

    @property
    def enabled(self) -> bool:
        return bool(self._token)

    def chats(self) -> set[str]:
        stored = json.loads(self._db.setting("tg_chats") or "[]")
        return set(self._env_chats) | {str(c) for c in stored}

    def _add_chat(self, chat_id: str) -> None:
        chats = json.loads(self._db.setting("tg_chats") or "[]")
        if chat_id not in chats:
            chats.append(chat_id)
            self._db.set_setting("tg_chats", json.dumps(chats))

    async def _call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        resp = await self._http.post(API.format(token=self._token, method=method), **kwargs)
        data = resp.json()
        if not data.get("ok"):
            log.warning("telegram_error method=%s error=%s", method, data.get("description"))
        return data

    async def send(self, text: str, key: str | None = None, every: int = 1800) -> None:
        """Сообщение всем подписанным админам. key — чтобы одинаковые алерты не сыпались чаще раза в `every` секунд."""
        if not self.enabled:
            return
        if key and self._db.hit(f"tg:{key}", every) > 1:
            return
        for chat in self.chats():
            try:
                await self._call("sendMessage", json={"chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True})
            except Exception as exc:  # noqa: BLE001 — уведомления не должны ронять сервер
                log.warning("telegram_send_failed error=%s", exc)

    async def send_file(self, filename: str, content: bytes, caption: str) -> bool:
        if not self.enabled or len(content) > MAX_DOCUMENT:
            return False
        sent = False
        for chat in self.chats():
            try:
                data = await self._call(
                    "sendDocument",
                    data={"chat_id": chat, "caption": caption[:1000], "parse_mode": "HTML"},
                    files={"document": (filename, content, "application/gzip")},
                )
                sent = sent or bool(data.get("ok"))
            except Exception as exc:  # noqa: BLE001
                log.warning("telegram_file_failed error=%s", exc)
        return sent

    async def poll_link(self) -> None:
        """Слушаем /start <код>, чтобы подключить чат админа. Без кода — молчим."""
        if not self.enabled or not self._link_code:
            return
        while True:
            try:
                data = await self._call("getUpdates", json={"offset": self._offset, "timeout": 25, "allowed_updates": ["message"]})
                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    message = update.get("message") or {}
                    text = str(message.get("text") or "").strip()
                    chat_id = str((message.get("chat") or {}).get("id") or "")
                    if not chat_id:
                        continue
                    if text == f"/start {self._link_code}":
                        await asyncio.to_thread(self._add_chat, chat_id)
                        await self._call("sendMessage", json={"chat_id": chat_id, "text": "✅ Подключено. Сюда будут приходить алерты, оплаты, сводка за день и бэкап базы «Книги моей жизни»."})
                        log.info("telegram_chat_linked chat=%s", chat_id)
                    elif chat_id in self.chats() and text == "/status":
                        await self.send(await asyncio.to_thread(status_text, self._db))
            except Exception as exc:  # noqa: BLE001
                log.warning("telegram_poll_failed error=%s", exc)
                await asyncio.sleep(15)

    async def close(self) -> None:
        await self._http.aclose()


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def status_text(db: Any, hours: int = 24) -> str:
    since = int(time.time()) - hours * 3600
    funnel = db.funnel(["visit", "book_created", "free_finished", "offer_view", "buy_click", "paid"], since)
    totals = db.totals()
    paid_today = db.paid_since(since)
    return (
        f"<b>📊 Книга моей жизни — за {hours} ч</b>\n"
        f"Визиты: {funnel.get('visit', 0)}\n"
        f"Начали книгу: {funnel.get('book_created', 0)}\n"
        f"12 бесплатных ответов: {funnel.get('free_finished', 0)}\n"
        f"Открыли предложение: {funnel.get('offer_view', 0)}\n"
        f"Нажали «Оплатить»: {funnel.get('buy_click', 0)}\n"
        f"Оплаты: <b>{paid_today['n']}</b> на {paid_today['sum']:.0f} ₽\n\n"
        f"Всего: {totals['paid']} оплат на {totals['revenue']:.0f} ₽, книг {totals['books']}"
    )


def backup_bytes(db: Any) -> bytes:
    """Согласованный снимок SQLite (без остановки сервера), сжатый gzip."""
    raw = db.snapshot()
    return gzip.compress(raw, compresslevel=6)
