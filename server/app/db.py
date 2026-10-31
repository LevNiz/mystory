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
CREATE TABLE IF NOT EXISTS chapter_photos (
    book_id     TEXT NOT NULL,
    id          TEXT NOT NULL,
    chapter_id  TEXT NOT NULL,
    src         TEXT NOT NULL,
    caption     TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (book_id, id)
);
CREATE INDEX IF NOT EXISTS chapter_photos_chapter ON chapter_photos (book_id, chapter_id, position);
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
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS promos (
    code        TEXT PRIMARY KEY,
    percent     INTEGER NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    note        TEXT NOT NULL DEFAULT '',
    visits      INTEGER NOT NULL DEFAULT 0,
    uniques     INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          INTEGER NOT NULL,
    visitor     TEXT,
    book_id     TEXT,
    name        TEXT NOT NULL,
    meta        TEXT
);
CREATE INDEX IF NOT EXISTS events_name_at ON events (name, at);
CREATE INDEX IF NOT EXISTS events_book ON events (book_id, at);
CREATE INDEX IF NOT EXISTS events_visitor ON events (visitor, at);
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
            # Фото из старой схемы (одно на главу) переносим в новую, где их может быть несколько.
            if not self._conn.execute("SELECT 1 FROM chapter_photos LIMIT 1").fetchone():
                self._conn.execute(
                    "INSERT OR IGNORE INTO chapter_photos (book_id, id, chapter_id, src, caption, position, updated_at) "
                    "SELECT book_id, chapter_id || '-1', chapter_id, src, caption, 1, updated_at FROM photos"
                )
            # Колонки, добавленные после первого запуска.
            for table, column in (
                ("payments", "email TEXT"), ("payments", "pay_url TEXT"), ("payments", "qr_link TEXT"),
                ("payments", "promo TEXT"), ("payments", "base_amount TEXT"),
                ("books", "visitor TEXT"), ("books", "source TEXT"), ("books", "last_seen INTEGER"),
                ("books", "last_ip TEXT"), ("books", "last_ua TEXT"),
            ):
                try:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
                except sqlite3.OperationalError:
                    pass

    def _q(self, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # --- Книги ---

    def create_book(self, book_id: str, token_hash: str, visitor: str | None = None, source: str | None = None) -> None:
        now = int(time.time())
        self._q(
            "INSERT INTO books (id, token_hash, visitor, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (book_id, token_hash, visitor, source, now, now),
        )

    def set_token(self, book_id: str, token_hash: str) -> None:
        self._q("UPDATE books SET token_hash = ? WHERE id = ?", (token_hash, book_id))

    def touch(self, book_id: str, ip: str, ua: str) -> None:
        self._q(
            "UPDATE books SET last_seen = ?, last_ip = ?, last_ua = ? WHERE id = ?",
            (int(time.time()), ip, ua, book_id),
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

    def photos(self, book_id: str) -> dict[str, list[dict[str, str]]]:
        """Фото книги по главам, в порядке добавления."""
        rows = self._q(
            "SELECT id, chapter_id, src, caption FROM chapter_photos WHERE book_id = ? ORDER BY chapter_id, position",
            (book_id,),
        )
        result: dict[str, list[dict[str, str]]] = {}
        for r in rows:
            result.setdefault(r["chapter_id"], []).append({"id": r["id"], "src": r["src"], "caption": r["caption"]})
        return result

    def photo_count(self, book_id: str, chapter_id: str) -> int:
        row = self._q("SELECT COUNT(*) AS n FROM chapter_photos WHERE book_id = ? AND chapter_id = ?", (book_id, chapter_id))
        return int(row[0]["n"])

    def add_photo(self, book_id: str, chapter_id: str, photo_id: str, src: str, caption: str) -> None:
        now = int(time.time())
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM chapter_photos WHERE book_id = ? AND chapter_id = ?",
                (book_id, chapter_id),
            ).fetchone()
            self._conn.execute(
                "INSERT INTO chapter_photos (book_id, id, chapter_id, src, caption, position, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (book_id, photo_id, chapter_id, src, caption, row[0], now),
            )

    def set_photo_caption(self, book_id: str, photo_id: str, caption: str) -> None:
        self._q(
            "UPDATE chapter_photos SET caption = ?, updated_at = ? WHERE book_id = ? AND id = ?",
            (caption, int(time.time()), book_id, photo_id),
        )

    def delete_photo(self, book_id: str, photo_id: str) -> None:
        self._q("DELETE FROM chapter_photos WHERE book_id = ? AND id = ?", (book_id, photo_id))

    # --- Платежи ---

    def add_payment(
        self,
        uuid: str,
        book_id: str,
        provider_id: int,
        amount: str,
        email: str,
        pay_url: str,
        qr_link: str | None,
        promo: str | None,
        base_amount: str,
    ) -> None:
        now = int(time.time())
        self._q(
            "INSERT INTO payments (uuid, book_id, provider_id, amount, email, pay_url, qr_link, promo, base_amount, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid, book_id, provider_id, amount, email, pay_url, qr_link, promo, base_amount, now, now),
        )

    def recent_payments(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self._q("SELECT * FROM payments ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def totals(self) -> dict[str, Any]:
        paid = self._q("SELECT COUNT(*) AS n, COALESCE(SUM(CAST(amount AS REAL)), 0) AS s FROM payments WHERE status = 'paid'")[0]
        books = self._q("SELECT COUNT(*) AS n, COALESCE(SUM(paid), 0) AS p FROM books")[0]
        return {"paid": paid["n"], "revenue": paid["s"], "books": books["n"], "paid_books": books["p"]}

    # --- Настройки и промокоды ---

    def setting(self, key: str) -> str | None:
        rows = self._q("SELECT value FROM settings WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def set_setting(self, key: str, value: str) -> None:
        self._q(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def promo(self, code: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM promos WHERE code = ?", (code,))
        return dict(rows[0]) if rows else None

    def add_promo(self, code: str, percent: int, note: str) -> bool:
        try:
            self._q(
                "INSERT INTO promos (code, percent, note, created_at) VALUES (?, ?, ?, ?)",
                (code, percent, note, int(time.time())),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def update_promo(self, code: str, percent: int, active: bool, note: str) -> None:
        self._q(
            "UPDATE promos SET percent = ?, active = ?, note = ? WHERE code = ?",
            (percent, int(active), note, code),
        )

    def promo_visit(self, code: str, unique: bool) -> None:
        self._q(
            "UPDATE promos SET visits = visits + 1, uniques = uniques + ? WHERE code = ?",
            (int(unique), code),
        )

    def promos_with_stats(self) -> list[dict[str, Any]]:
        rows = self._q(
            """SELECT p.*,
                      COUNT(pay.uuid) AS checkouts,
                      COALESCE(SUM(pay.status = 'paid'), 0) AS paid,
                      COALESCE(SUM(CASE WHEN pay.status = 'paid' THEN CAST(pay.amount AS REAL) END), 0) AS revenue
               FROM promos p LEFT JOIN payments pay ON pay.promo = p.code
               GROUP BY p.code ORDER BY p.created_at DESC"""
        )
        return [dict(r) for r in rows]

    def open_payment(self, book_id: str, max_age: int) -> dict[str, Any] | None:
        """Последний неоплаченный платёж книги — чтобы не плодить счета при повторном нажатии."""
        rows = self._q(
            "SELECT * FROM payments WHERE book_id = ? AND status = 'pending' AND created_at > ? "
            "ORDER BY created_at DESC LIMIT 1",
            (book_id, int(time.time()) - max_age),
        )
        return dict(rows[0]) if rows else None

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

    def recent_pending(self, max_age: int) -> list[dict[str, Any]]:
        rows = self._q(
            "SELECT * FROM payments WHERE status = 'pending' AND created_at > ? ORDER BY created_at DESC LIMIT 50",
            (int(time.time()) - max_age,),
        )
        return [dict(r) for r in rows]

    def set_payment_status(self, uuid: str, status: str) -> None:
        self._q(
            "UPDATE payments SET status = ?, updated_at = ? WHERE uuid = ?",
            (status, int(time.time()), uuid),
        )

    # --- События (путь пользователя) ---

    def add_event(self, name: str, visitor: str | None, book_id: str | None, meta: dict[str, Any] | None = None) -> None:
        self._q(
            "INSERT INTO events (at, visitor, book_id, name, meta) VALUES (?, ?, ?, ?, ?)",
            (int(time.time()), visitor, book_id, name, json.dumps(meta, ensure_ascii=False) if meta else None),
        )

    def visitor_source(self, visitor: str | None) -> str | None:
        if not visitor:
            return None
        rows = self._q(
            "SELECT json_extract(meta, '$.source') AS source FROM events WHERE visitor = ? AND name = 'visit' ORDER BY at LIMIT 1",
            (visitor,),
        )
        return rows[0]["source"] if rows else None

    def funnel(self, names: list[str], since: int) -> dict[str, int]:
        """Уникальные посетители (или книги без посетителя) по каждому шагу за период."""
        marks = ",".join("?" * len(names))
        rows = self._q(
            f"SELECT name, COUNT(DISTINCT COALESCE(visitor, book_id)) AS n FROM events "
            f"WHERE at >= ? AND name IN ({marks}) GROUP BY name",
            (since, *names),
        )
        return {r["name"]: r["n"] for r in rows}

    def event_counts(self, since: int) -> list[dict[str, Any]]:
        rows = self._q(
            "SELECT name, COUNT(*) AS total, COUNT(DISTINCT COALESCE(visitor, book_id)) AS people "
            "FROM events WHERE at >= ? GROUP BY name ORDER BY total DESC",
            (since,),
        )
        return [dict(r) for r in rows]

    def sources(self, since: int) -> list[dict[str, Any]]:
        rows = self._q(
            """SELECT COALESCE(json_extract(v.meta, '$.source'), 'прямой заход') AS source,
                      COUNT(DISTINCT v.visitor) AS visitors,
                      COUNT(DISTINCT b.visitor) AS started,
                      COUNT(DISTINCT CASE WHEN p.name = 'paid' THEN p.visitor END) AS paid
               FROM events v
               LEFT JOIN events b ON b.visitor = v.visitor AND b.name = 'book_created'
               LEFT JOIN events p ON p.visitor = v.visitor AND p.name = 'paid'
               WHERE v.name = 'visit' AND v.at >= ? AND v.visitor IS NOT NULL
               GROUP BY source ORDER BY visitors DESC LIMIT 20""",
            (since,),
        )
        return [dict(r) for r in rows]

    def daily(self, days: int) -> list[dict[str, Any]]:
        since = int(time.time()) - days * 86_400
        rows = self._q(
            """SELECT date(at, 'unixepoch', '+3 hours') AS day,
                      COUNT(DISTINCT CASE WHEN name = 'visit' THEN visitor END) AS visits,
                      COUNT(DISTINCT CASE WHEN name = 'book_created' THEN book_id END) AS books,
                      COUNT(DISTINCT CASE WHEN name = 'free_finished' THEN book_id END) AS free_done,
                      COUNT(DISTINCT CASE WHEN name = 'offer_view' THEN COALESCE(visitor, book_id) END) AS offers,
                      COUNT(DISTINCT CASE WHEN name = 'paid' THEN book_id END) AS paid
               FROM events WHERE at >= ? GROUP BY day ORDER BY day DESC""",
            (since,),
        )
        return [dict(r) for r in rows]

    def recent_books(self, limit: int = 40) -> list[dict[str, Any]]:
        rows = self._q(
            """SELECT b.id, b.created_at, b.paid, b.source, b.last_seen, b.data,
                      (SELECT GROUP_CONCAT(name, ' → ') FROM (SELECT name FROM events e WHERE e.book_id = b.id ORDER BY e.at DESC LIMIT 6)) AS last_events,
                      (SELECT promo FROM payments p WHERE p.book_id = b.id AND p.promo IS NOT NULL LIMIT 1) AS promo
               FROM books b ORDER BY COALESCE(b.last_seen, b.updated_at) DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in rows]

    def book_timeline(self, book_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM books WHERE id = ?", (book_id,))
        if not rows:
            return None
        book = dict(rows[0])
        visitor = book.get("visitor")
        events = self._q(
            "SELECT at, name, meta FROM events WHERE book_id = ? OR (visitor IS NOT NULL AND visitor = ?) ORDER BY at, id",
            (book_id, visitor),
        )
        pays = self._q("SELECT * FROM payments WHERE book_id = ? ORDER BY created_at", (book_id,))
        photos = self._q("SELECT chapter_id, COUNT(*) AS n FROM chapter_photos WHERE book_id = ? GROUP BY chapter_id", (book_id,))
        return {
            "book": book,
            "events": [dict(e) for e in events],
            "payments": [dict(p) for p in pays],
            "photos": {r["chapter_id"]: r["n"] for r in photos},
        }

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
