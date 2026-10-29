"""SQLite-хранилище: книги, фото, платежи и счётчики лимитов.

Запросы короткие, поэтому выполняем их синхронно в пуле потоков (asyncio.to_thread).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id          TEXT PRIMARY KEY,
    token_hash  TEXT NOT NULL UNIQUE,
    data        TEXT NOT NULL DEFAULT '{}',
    ai          TEXT NOT NULL DEFAULT '{}',
    paid        INTEGER NOT NULL DEFAULT 0,
    paid_at     INTEGER,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS photos (
    book_id     TEXT NOT NULL,
    chapter_id  TEXT NOT NULL,
    src         TEXT NOT NULL,
    caption     TEXT NOT NULL DEFAULT '',
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (book_id, chapter_id)
);
CREATE TABLE IF NOT EXISTS payments (
    uuid        TEXT PRIMARY KEY,
    book_id     TEXT NOT NULL,
    provider_id INTEGER,
    amount      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS payments_book ON payments (book_id, status);
CREATE TABLE IF NOT EXISTS counters (
    key         TEXT PRIMARY KEY,
    value       INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)

    def _q(self, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # --- Книги ---

    def create_book(self, book_id: str, token_hash: str) -> None:
        now = int(time.time())
        self._q(
            "INSERT INTO books (id, token_hash, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (book_id, token_hash, now, now),
        )

    def book_by_token(self, token_hash: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM books WHERE token_hash = ?", (token_hash,))
        return _book(rows[0]) if rows else None

    def book_by_id(self, book_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM books WHERE id = ?", (book_id,))
        return _book(rows[0]) if rows else None

    def save_data(self, book_id: str, data: dict[str, Any]) -> None:
        self._q(
            "UPDATE books SET data = ?, updated_at = ? WHERE id = ?",
            (json.dumps(data, ensure_ascii=False), int(time.time()), book_id),
        )

    def save_ai(self, book_id: str, ai: dict[str, Any]) -> None:
        self._q(
            "UPDATE books SET ai = ?, updated_at = ? WHERE id = ?",
            (json.dumps(ai, ensure_ascii=False), int(time.time()), book_id),
        )

    def mark_paid(self, book_id: str) -> None:
        self._q(
            "UPDATE books SET paid = 1, paid_at = COALESCE(paid_at, ?) WHERE id = ?",
            (int(time.time()), book_id),
        )

    # --- Фото ---

    def photos(self, book_id: str) -> dict[str, dict[str, str]]:
        rows = self._q("SELECT chapter_id, src, caption FROM photos WHERE book_id = ?", (book_id,))
        return {r["chapter_id"]: {"src": r["src"], "caption": r["caption"]} for r in rows}

    def put_photo(self, book_id: str, chapter_id: str, src: str | None, caption: str) -> None:
        now = int(time.time())
        if src is None:
            self._q(
                "UPDATE photos SET caption = ?, updated_at = ? WHERE book_id = ? AND chapter_id = ?",
                (caption, now, book_id, chapter_id),
            )
            return
        self._q(
            "INSERT INTO photos (book_id, chapter_id, src, caption, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (book_id, chapter_id) DO UPDATE SET src = excluded.src, "
            "caption = excluded.caption, updated_at = excluded.updated_at",
            (book_id, chapter_id, src, caption, now),
        )

    def delete_photo(self, book_id: str, chapter_id: str) -> None:
        self._q("DELETE FROM photos WHERE book_id = ? AND chapter_id = ?", (book_id, chapter_id))

    # --- Платежи ---

    def add_payment(self, uuid: str, book_id: str, provider_id: int, amount: str) -> None:
        now = int(time.time())
        self._q(
            "INSERT INTO payments (uuid, book_id, provider_id, amount, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uuid, book_id, provider_id, amount, now, now),
        )

    def payment(self, uuid: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM payments WHERE uuid = ?", (uuid,))
        return dict(rows[0]) if rows else None

    def pending_payments(self, book_id: str, max_age: int) -> list[dict[str, Any]]:
        rows = self._q(
            "SELECT * FROM payments WHERE book_id = ? AND status = 'pending' AND created_at > ? "
            "ORDER BY created_at DESC LIMIT 5",
            (book_id, int(time.time()) - max_age),
        )
        return [dict(r) for r in rows]

    def set_payment_status(self, uuid: str, status: str) -> None:
        self._q(
            "UPDATE payments SET status = ?, updated_at = ? WHERE uuid = ?",
            (status, int(time.time()), uuid),
        )

    # --- Лимиты ---

    def hit(self, key: str, window: int) -> int:
        """Увеличивает счётчик в окне `window` секунд и возвращает новое значение."""
        now = int(time.time())
        with self._lock:
            self._conn.execute("DELETE FROM counters WHERE expires_at <= ?", (now,))
            self._conn.execute(
                "INSERT INTO counters (key, value, expires_at) VALUES (?, 1, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = value + 1",
                (key, now + window),
            )
            row = self._conn.execute("SELECT value FROM counters WHERE key = ?", (key,)).fetchone()
        return int(row["value"])


def _book(row: sqlite3.Row) -> dict[str, Any]:
    book = dict(row)
    book["data"] = json.loads(book["data"] or "{}")
    book["ai"] = json.loads(book["ai"] or "{}")
    book["paid"] = bool(book["paid"])
    return book
