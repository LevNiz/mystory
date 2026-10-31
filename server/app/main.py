"""Сервер «Книги моей жизни»: синхронизация книги, ИИ-обработка текста, оплата и статика сайта.

Идентификация анонимная: при первом сохранении создаём книгу и кладём случайный токен
в httpOnly-cookie. В базе хранится только хэш токена. Никаких секретов во фронтенде.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import secrets
import time
import uuid as uuid_lib
from html import escape as html_escape
from urllib.parse import urlparse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import segno
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .admin import build_router as admin_router
from .analytics import CLIENT_EVENTS, clean_meta, milestones, visit_source
from .ai import AIBusy, AIClient, AIError
from .config import load_settings
from .content import Content, gendered
from .db import Database
from .pricing import PROMO_COOKIE, normalize_code, quote
from .urlpay import UrlPay, verdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("mystory")

settings = load_settings()
db = Database(settings.db_path)
content = Content(settings.web_dir / "js" / "questions.js")
FULL_QUESTIONS = sum(len(c.questions) for cid, c in content.full_chapters.items() if cid != "intro")
urlpay = (
    UrlPay(settings.urlpay_api_key, settings.urlpay_secret_key, settings.urlpay_shop_id)
    if settings.payments_enabled
    else None
)
ai: AIClient | None = None

# Префикс __Host- (только по HTTPS): cookie нельзя подложить с поддомена или задать для другого пути.
COOKIE = "__Host-ms_book" if settings.cookie_secure else "ms_book"
LEGACY_COOKIE = "ms_book"
VISITOR_COOKIE = "__Host-ms_vid" if settings.cookie_secure else "ms_vid"
VISITOR_ID = re.compile(r"^[A-Za-z0-9_-]{16,40}$")
COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 2
MAX_STATE_BYTES = 600_000
MAX_PHOTO_BYTES = 3_000_000
DAY = 86_400

# Лимиты на книгу в сутки и на IP в час — защищают бюджет ИИ от злоупотреблений.
LIMITS = {
    "chapter": {"free": 15, "paid": 150},
    "followup": {"free": 80, "paid": 400},
}
AI_PER_IP_HOUR = 200
BOOKS_PER_IP_HOUR = 30
BOOKS_PER_IP_DAY = 100
STATE_SAVES_PER_BOOK_10MIN = 400
EVENTS_PER_VISITOR_HOUR = 400
PAYMENTS_PER_EMAIL_DAY = 5
PAYMENTS_PER_IP_DAY = 30
RECOVERY_PER_IP_HOUR = 60
PAYMENTS_PER_BOOK_HOUR = 10

PAYMENT_DESCRIPTION = "Полная книга моей жизни"
CHAPTER_ID = re.compile(r"^[a-z]{2,12}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
QUESTION_ID = re.compile(r"^[a-z0-9-]{2,20}$")


async def payment_watcher() -> None:
    """Раз в минуту спрашиваем UrlPay о свежих неоплаченных платежах.

    Уведомления магазина уходят на адрес wgpt_bot, поэтому оплату подтверждаем сами —
    даже если человек закрыл вкладку сразу после оплаты.
    """
    while True:
        await asyncio.sleep(60)
        try:
            for payment in await asyncio.to_thread(db.recent_pending, 2 * DAY):
                await check_payment(payment)
        except Exception:  # noqa: BLE001
            log.exception("payment_watcher_failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global ai
    if settings.ai_enabled:
        ai = AIClient(
            settings.ai_base_url,
            settings.ai_api_key,
            settings.ai_model,
            settings.ai_chapter_model,
            settings.ai_timeout,
            settings.ai_max_concurrent,
        )
    log.info("start ai=%s payments=%s", bool(ai), bool(urlpay))
    watcher = asyncio.create_task(payment_watcher()) if urlpay else None
    yield
    if watcher:
        watcher.cancel()
    if ai:
        await ai.close()


app = FastAPI(title="mystory", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


# ---------- Безопасность ----------

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' https://cdnjs.cloudflare.com https://mc.yandex.ru https://yastatic.net",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: blob: https://mc.yandex.ru https://mc.yandex.com",
        "connect-src 'self' https://mc.yandex.ru https://mc.yandex.com wss://mc.yandex.ru",
        "frame-src https://mc.yandex.ru https://mc.yandex.com",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
    ]
)


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    mutating = request.method in {"POST", "PUT", "DELETE", "PATCH"}
    if mutating and (path.startswith("/api/") or path.startswith("/r/")):
        # Защита от CSRF: запрос должен прийти с нашего же сайта.
        if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host", ""):
            return JSONResponse({"error": "forbidden"}, status_code=403)
    if path.startswith("/api/") and mutating:
        # Кросс-сайтовая форма не может выставить этот заголовок.
        if request.headers.get("x-requested-with") != "mystory":
            return JSONResponse({"error": "forbidden"}, status_code=403)
        limit = MAX_PHOTO_BYTES + 50_000 if path.startswith("/api/photo/") else MAX_STATE_BYTES
        # Потоковые тела без Content-Length дополнительно ограничивает nginx (client_max_body_size).
        length = request.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > limit):
            return JSONResponse({"error": "too_large"}, status_code=413)

    response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"
    response.headers["Content-Security-Policy"] = CSP
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

    # Переезд со старой cookie на __Host- и выдача идентификатора посетителя.
    renew = getattr(request.state, "renew_token", None)
    if renew:
        set_cookie(response, renew)
        response.delete_cookie(LEGACY_COOKIE, path="/")
    new_visitor = getattr(request.state, "new_visitor", None)
    if new_visitor:
        response.set_cookie(
            VISITOR_COOKIE, new_visitor, max_age=COOKIE_MAX_AGE, httponly=True,
            secure=settings.cookie_secure, samesite="lax", path="/",
        )
    # HSTS ставит общий nginx (snippets/ssl-params.conf), чтобы заголовок не дублировался.

    if path.startswith("/api/") or path.startswith("/r/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex"
    elif path.startswith(("/css/", "/js/", "/img/")):
        versioned = "v" in request.query_params
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if versioned else "public, max-age=3600"
    elif path.endswith(".html") or path == "/":
        response.headers["Cache-Control"] = "no-cache"
    return response


def client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def full_free() -> bool:
    """Режим из админки: полная книга открыта всем без оплаты."""
    return db.setting("full_free") == "1"


def current_book(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(COOKIE)
    if not token and COOKIE != LEGACY_COOKIE:
        token = request.cookies.get(LEGACY_COOKIE)
        if token:
            request.state.renew_token = token
    if not token or len(token) > 100:
        return None
    book = db.book_by_token(token_hash(token))
    if book is not None:
        # purchased — реальная оплата; paid — доступ к полной книге (оплата или бесплатный режим).
        book["purchased"] = book["paid"]
        book["paid"] = book["paid"] or full_free()
    return book


def visitor_id(request: Request) -> str:
    """Анонимный идентификатор посетителя — чтобы видеть путь ещё до создания книги."""
    vid = request.cookies.get(VISITOR_COOKIE, "")
    if not VISITOR_ID.match(vid):
        vid = getattr(request.state, "new_visitor", None) or secrets.token_urlsafe(18)
        request.state.new_visitor = vid
    return vid


def track(name: str, request: Request | None, book: dict[str, Any] | None = None, meta: dict[str, Any] | None = None) -> None:
    visitor = visitor_id(request) if request is not None else (book or {}).get("visitor")
    db.add_event(name, visitor, book["id"] if book else None, meta)


def short_ip(ip: str) -> str:
    """IP без последнего октета — для админки достаточно, полный адрес не храним."""
    if ":" in ip:
        return ":".join(ip.split(":")[:3]) + "::"
    parts = ip.split(".")
    return ".".join(parts[:3] + ["0"]) if len(parts) == 4 else ip[:40]


def set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def require_book(request: Request) -> dict[str, Any]:
    book = current_book(request)
    if book is None:
        raise HTTPException(status_code=401, detail="no_book")
    return book


def rate(key: str, window: int, limit: int) -> None:
    if db.hit(key, window) > limit:
        raise HTTPException(status_code=429, detail="rate_limited")


async def read_json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="bad_json") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="bad_json")
    return body


def public_state(book: dict[str, Any] | None) -> dict[str, Any]:
    if book is None:
        return {"exists": False, "paid": full_free(), "purchased": False, "data": None, "ai": {}, "photos": {}}
    return {
        "exists": True,
        "paid": book["paid"],
        "purchased": book["purchased"],
        "data": book["data"],
        "ai": book["ai"],
        "photos": db.photos(book["id"]),
    }


def price_quote(request: Request) -> dict[str, Any]:
    return quote(db, settings.price_rub, request.cookies.get(PROMO_COOKIE))


def features(request: Request) -> dict[str, Any]:
    return {"ai": bool(ai), "payments": bool(urlpay), "fullFree": full_free(), **price_quote(request)}


# ---------- Книга ----------


@app.get("/api/state")
async def get_state(request: Request) -> dict[str, Any]:
    book = await asyncio.to_thread(current_book, request)
    visitor_id(request)
    return {**public_state(book), "features": features(request)}


@app.put("/api/state")
async def put_state(request: Request) -> Response:
    body = await read_json(request)
    data = body.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="bad_data")
    data.pop("paid", None)  # статус оплаты знает только сервер
    data.pop("events", None)  # события теперь пишутся на сервере, а не в книге

    book = await asyncio.to_thread(current_book, request)
    response = JSONResponse({"ok": True})
    ip = client_ip(request)
    if book is None:
        rate(f"books:{ip}", 3600, BOOKS_PER_IP_HOUR)
        rate(f"books-day:{ip}", DAY, BOOKS_PER_IP_DAY)
        token = secrets.token_urlsafe(32)
        book_id = str(uuid_lib.uuid4())
        vid = visitor_id(request)
        await asyncio.to_thread(db.create_book, book_id, token_hash(token), vid, db.visitor_source(vid))
        set_cookie(response, token)
        book = {"id": book_id, "data": {}, "visitor": vid}
        track("book_created", request, book)
    else:
        book_id = book["id"]
        rate(f"saves:{book_id}", 600, STATE_SAVES_PER_BOOK_10MIN)
    for name in milestones(book.get("data") or {}, data, FULL_QUESTIONS):
        track(name, request, book)
    await asyncio.to_thread(db.save_data, book_id, data)
    await asyncio.to_thread(db.touch, book_id, short_ip(ip), request.headers.get("user-agent", "")[:160])
    return response


@app.post("/api/event")
async def client_event(request: Request) -> dict[str, bool]:
    """События интерфейса из белого списка (то, что сервер сам не видит)."""
    body = await read_json(request)
    name = str(body.get("name") or "")
    if name not in CLIENT_EVENTS:
        raise HTTPException(status_code=400, detail="bad_event")
    vid = visitor_id(request)
    rate(f"events:{vid}", 3600, EVENTS_PER_VISITOR_HOUR)
    rate(f"events-ip:{client_ip(request)}", 3600, EVENTS_PER_VISITOR_HOUR * 3)
    meta = clean_meta(body.get("meta"))
    if name == "visit":
        meta["source"] = visit_source(meta, urlparse(settings.public_url).netloc)
    book = await asyncio.to_thread(current_book, request)
    await asyncio.to_thread(track, name, request, book, meta or None)
    return {"ok": True}


MAX_PHOTOS_PER_CHAPTER = 6
PHOTO_ID = re.compile(r"^[a-z]{2,12}-[A-Za-z0-9_-]{1,24}$")


@app.post("/api/photo/{chapter_id}")
async def add_photo(chapter_id: str, request: Request) -> dict[str, str]:
    """Новое фото в главу (их может быть несколько)."""
    book = require_book(request)
    if not book["paid"]:
        raise HTTPException(status_code=402, detail="paid_only")
    if chapter_id not in content.full_chapters:
        raise HTTPException(status_code=404, detail="unknown_chapter")
    body = await read_json(request)
    src = body.get("src")
    if not isinstance(src, str) or not re.match(r"^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$", src):
        raise HTTPException(status_code=400, detail="bad_image")
    if len(src) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="too_large")
    if await asyncio.to_thread(db.photo_count, book["id"], chapter_id) >= MAX_PHOTOS_PER_CHAPTER:
        raise HTTPException(status_code=409, detail="too_many_photos")
    photo_id = f"{chapter_id}-{secrets.token_urlsafe(6)}"
    await asyncio.to_thread(db.add_photo, book["id"], chapter_id, photo_id, src, str(body.get("caption") or "")[:200])
    track("photo_added", request, book, {"chapter": chapter_id})
    return {"id": photo_id}


@app.put("/api/photo/{chapter_id}/{photo_id}")
async def edit_photo(chapter_id: str, photo_id: str, request: Request) -> dict[str, bool]:
    book = require_book(request)
    if not PHOTO_ID.match(photo_id):
        raise HTTPException(status_code=400, detail="bad_photo")
    body = await read_json(request)
    await asyncio.to_thread(db.set_photo_caption, book["id"], photo_id, str(body.get("caption") or "")[:200])
    return {"ok": True}


@app.delete("/api/photo/{chapter_id}/{photo_id}")
async def delete_photo(chapter_id: str, photo_id: str, request: Request) -> dict[str, bool]:
    book = require_book(request)
    if not PHOTO_ID.match(photo_id):
        raise HTTPException(status_code=400, detail="bad_photo")
    await asyncio.to_thread(db.delete_photo, book["id"], photo_id)
    return {"ok": True}


@app.get("/api/recovery-link")
async def recovery_link(request: Request) -> dict[str, str]:
    require_book(request)
    token = request.cookies.get(COOKIE) or getattr(request.state, "renew_token", "")
    return {"url": f"{settings.public_url}/r/{token}"}


@app.post("/api/recovery-link/rotate")
async def rotate_recovery_link(request: Request) -> Response:
    """Новая личная ссылка: старая перестаёт открывать книгу (если ею поделились случайно)."""
    book = require_book(request)
    rate(f"rotate:{book['id']}", 3600, 10)
    token = secrets.token_urlsafe(32)
    await asyncio.to_thread(db.set_token, book["id"], token_hash(token))
    track("link_rotated", request, book)
    response = JSONResponse({"url": f"{settings.public_url}/r/{token}"})
    set_cookie(response, token)
    return response


def recovery_page(title: str, author: str, token: str, replacing: bool) -> str:
    warn = (
        "<p class='warn'>В этом браузере уже открыта другая книга. После перехода она останется на сервере, "
        "но открыть её снова получится только по её личной ссылке.</p>"
        if replacing
        else ""
    )
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Открыть книгу — Книга моей жизни</title><link rel="stylesheet" href="/css/styles.css">
</head><body><main class="lost"><div class="lost__card">
<p class="lost__code">Личная ссылка</p>
<h1>Открыть книгу <em>«{html_escape(title)}»</em></h1>
<p>{html_escape(author) + " · " if author else ""}Продолжай только если это твоя книга. Не открывай личные ссылки, которые прислали незнакомые люди: всё, что ты напишешь, увидит владелец ссылки.</p>
{warn}
<form class="lost__actions" method="post" action="/r/{token}">
  <button class="btn btn--dark btn--lg" type="submit">Да, открыть мою книгу</button>
  <a class="btn btn--ghost btn--lg" href="/">Отмена</a>
</form></div></main></body></html>"""


@app.get("/r/{token}")
async def recover(token: str, request: Request) -> Response:
    rate(f"recover:{client_ip(request)}", 3600, RECOVERY_PER_IP_HOUR)
    target = db.book_by_token(token_hash(token)) if len(token) <= 100 else None
    if target is None:
        return RedirectResponse("/#/", status_code=302)
    current = current_book(request)
    if current and current["id"] == target["id"]:
        return RedirectResponse("/#/book", status_code=302)
    # Не подменяем книгу молча: страница подтверждения защищает от фишинговых ссылок
    # (злоумышленник присылает ссылку на свою книгу и читает, что в неё напишут).
    data = target.get("data") or {}
    title = str((data.get("book") or {}).get("title") or "").strip() or "Моя история"
    author = str((data.get("profile") or {}).get("name") or "").strip()
    page = recovery_page(title, author, token, replacing=current is not None)
    return HTMLResponse(page, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@app.post("/r/{token}")
async def recover_confirm(token: str, request: Request) -> Response:
    rate(f"recover:{client_ip(request)}", 3600, RECOVERY_PER_IP_HOUR)
    target = db.book_by_token(token_hash(token)) if len(token) <= 100 else None
    if target is None:
        return RedirectResponse("/#/", status_code=303)
    response = RedirectResponse("/#/book", status_code=303)
    set_cookie(response, token)
    track("recovered", request, target)
    return response


# ---------- ИИ ----------


def ai_quota(book: dict[str, Any], kind: str, request: Request) -> None:
    if ai is None:
        raise HTTPException(status_code=503, detail="ai_disabled")
    rate(f"ai-ip:{client_ip(request)}", 3600, AI_PER_IP_HOUR)
    tier = "paid" if book["paid"] else "free"
    rate(f"ai-{kind}:{book['id']}:{time.strftime('%Y%m%d')}", DAY, LIMITS[kind][tier])


def chapter_pairs(book: dict[str, Any], edition: str, chapter_id: str) -> tuple[str, list[tuple[str, str]], str]:
    chapter = content.chapter(edition, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="unknown_chapter")
    data = book["data"]
    gender = (data.get("profile") or {}).get("gender", "m")
    answers = data.get("answers") or {}
    pairs: list[tuple[str, str]] = []
    for q in chapter.questions:
        a = answers.get(q.id) or {}
        text = str(a.get("text") or "").strip()
        if text and not a.get("excluded"):
            pairs.append((gendered(q.title, gender), text[:6000]))
    return gendered(chapter.title, gender), pairs, gender


# Ответы, по которым видно характер человека: как он представляется, три слова о себе,
# история, которую он рассказывает о себе, и глава «Какой я на самом деле».
PORTRAIT_QUESTIONS = ("f1", "f2", "f3", "self-1", "self-2", "self-5", "self-10")


def author_portrait(book: dict[str, Any]) -> str:
    data = book["data"]
    profile = data.get("profile") or {}
    gender = profile.get("gender", "m")
    lines = []
    if profile.get("name"):
        lines.append(f"Имя: {str(profile['name'])[:80]}")
    born, city = str(profile.get("born") or "")[:4], str(profile.get("city") or "")[:80]
    if born or city:
        lines.append(gendered("{Родился|Родилась}: ", gender) + ", ".join(x for x in (f"{born} год" if born else "", city) if x))
    answers = data.get("answers") or {}
    for qid in PORTRAIT_QUESTIONS:
        text = str((answers.get(qid) or {}).get("text") or "").strip()
        question = content.questions.get(qid)
        if text and question:
            lines.append(f"{gendered(question.title, gender)} — {text[:600]}")
    return "\n".join(lines)[:3000]


@app.post("/api/ai/chapter")
async def ai_chapter(request: Request) -> dict[str, Any]:
    book = require_book(request)
    body = await read_json(request)
    edition = "full" if body.get("edition") == "full" else "free"
    chapter_id = str(body.get("chapterId") or "")
    if not CHAPTER_ID.match(chapter_id):
        raise HTTPException(status_code=400, detail="bad_chapter")
    if edition == "full" and not book["paid"]:
        raise HTTPException(status_code=402, detail="paid_only")

    title, pairs, gender = chapter_pairs(book, edition, chapter_id)
    if not pairs:
        raise HTTPException(status_code=400, detail="no_answers")
    portrait = author_portrait(book)
    photos = (await asyncio.to_thread(db.photos, book["id"])).get(chapter_id, []) if edition == "full" else []
    captions = [p["caption"] or "фотография к главе" for p in photos]
    source = hashlib.sha256(json.dumps([pairs, gender, portrait, captions], ensure_ascii=False).encode()).hexdigest()[:16]
    key = f"{edition}:{chapter_id}"

    cached = book["ai"].get(key)
    if cached and cached.get("source") == source and not body.get("force"):
        return cached

    ai_quota(book, "chapter", request)
    try:
        text = await ai.chapter(title, pairs, gender, portrait, captions)  # type: ignore[union-attr]
    except AIBusy:
        raise HTTPException(status_code=503, detail="ai_busy") from None
    except AIError:
        raise HTTPException(status_code=502, detail="ai_failed") from None
    if not text:
        raise HTTPException(status_code=502, detail="ai_empty")

    track("ai_chapter", request, book, {"chapter": chapter_id})
    entry = {"text": text[:30000], "source": source, "at": int(time.time()), "edited": False}
    fresh = await asyncio.to_thread(db.book_by_id, book["id"])
    ai_state = (fresh or book)["ai"]
    ai_state[key] = entry
    await asyncio.to_thread(db.save_ai, book["id"], ai_state)
    return entry


@app.put("/api/ai/chapter")
async def ai_chapter_edit(request: Request) -> dict[str, bool]:
    """Ручная правка литературного текста главы (или удаление: text = null)."""
    book = require_book(request)
    body = await read_json(request)
    key = str(body.get("key") or "")
    if not re.match(r"^(free|full):[a-z]{2,12}$", key):
        raise HTTPException(status_code=400, detail="bad_key")
    ai_state = book["ai"]
    if body.get("text") is None:
        ai_state.pop(key, None)
    elif key in ai_state:
        ai_state[key] = {**ai_state[key], "text": str(body["text"])[:30000], "edited": True}
    await asyncio.to_thread(db.save_ai, book["id"], ai_state)
    return {"ok": True}


@app.post("/api/ai/followup")
async def ai_followup(request: Request) -> dict[str, list[str]]:
    book = require_book(request)
    body = await read_json(request)
    qid = str(body.get("questionId") or "")
    answer = str(body.get("text") or "").strip()[:4000]
    question = content.questions.get(qid) if QUESTION_ID.match(qid) else None
    if question is None:
        raise HTTPException(status_code=400, detail="bad_question")
    if not question.free and not book["paid"]:
        raise HTTPException(status_code=402, detail="paid_only")
    if len(answer) < 20:
        return {"questions": []}
    ai_quota(book, "followup", request)
    gender = (book["data"].get("profile") or {}).get("gender", "m")
    try:
        questions = await ai.followups(gendered(question.title, gender), answer, gender)  # type: ignore[union-attr]
    except AIBusy:
        raise HTTPException(status_code=503, detail="ai_busy") from None
    except AIError:
        raise HTTPException(status_code=502, detail="ai_failed") from None
    track("ai_followup", request, book)
    return {"questions": questions}


# ---------- Оплата ----------


async def check_payment(payment: dict[str, Any]) -> str:
    """Спрашиваем статус у UrlPay и, если оплачено, открываем полную книгу."""
    if urlpay is None or not payment.get("provider_id"):
        return "pending"
    try:
        remote = await urlpay.get(int(payment["provider_id"]))
    except Exception as exc:  # noqa: BLE001 — сетевые ошибки провайдера не должны ронять запрос
        log.warning("urlpay_check_failed uuid=%s error=%s", payment["uuid"], exc)
        return "pending"
    result = verdict(
        remote,
        payment["uuid"],
        int(payment["provider_id"]),
        payment["amount"],
        settings.urlpay_paid_statuses,
        settings.urlpay_failed_statuses,
    )
    log.info(
        "urlpay_check uuid=%s result=%s status_fields=%s",
        payment["uuid"],
        result,
        {k: remote.get(k) for k in ("status", "payment_status", "state") if k in remote},
    )
    if result in {"paid", "failed", "mismatch"}:
        book = await asyncio.to_thread(db.book_by_id, payment["book_id"])
        meta = {"amount": payment["amount"], "promo": payment.get("promo")}
        if result == "paid":
            await asyncio.to_thread(db.set_payment_status, payment["uuid"], "paid")
            await asyncio.to_thread(db.mark_paid, payment["book_id"])
            await asyncio.to_thread(track, "paid", None, book, meta)
        else:
            await asyncio.to_thread(db.set_payment_status, payment["uuid"], result)
            await asyncio.to_thread(track, "payment_failed", None, book, {**meta, "status": result})
    return result


def checkout(payment: dict[str, Any]) -> dict[str, Any]:
    """Данные для нашей страницы оплаты: сумма, e-mail для чека, ссылка СБП и QR."""
    qr_svg = None
    if payment.get("qr_link"):
        qr_svg = segno.make(payment["qr_link"], error="m").svg_data_uri(scale=6, border=2, dark="#16171b")
    return {
        "amount": payment["amount"],
        "email": payment.get("email") or "",
        "sbpLink": payment.get("qr_link"),
        "qr": qr_svg,
        "payUrl": payment.get("pay_url"),
        "createdAt": payment["created_at"],
    }


@app.post("/api/pay")
async def pay(request: Request) -> dict[str, Any]:
    book = require_book(request)
    if book["paid"]:
        return {"paid": True}
    if urlpay is None:
        raise HTTPException(status_code=503, detail="payments_disabled")
    body = await read_json(request)
    email = str(body.get("email") or "").strip().lower()
    if len(email) > 120 or not EMAIL.match(email):
        raise HTTPException(status_code=400, detail="bad_email")

    offer = await asyncio.to_thread(price_quote, request)
    amount = offer["price"]
    promo_code = offer["promo"]["code"] if offer["promo"] else None

    # Повторное нажатие в течение 15 минут возвращает тот же счёт, если цена и e-mail не менялись.
    existing = await asyncio.to_thread(db.open_payment, book["id"], 15 * 60)
    if existing and existing.get("email") == email and existing["amount"] == amount and existing.get("qr_link"):
        return {"paid": False, "checkout": checkout(existing)}

    rate(f"pay:{book['id']}", 3600, PAYMENTS_PER_BOOK_HOUR)
    # Против спама чеками: на один e-mail и с одного IP — ограниченное число счетов в сутки.
    rate(f"pay-email:{hashlib.sha256(email.encode()).hexdigest()[:20]}", DAY, PAYMENTS_PER_EMAIL_DAY)
    rate(f"pay-ip:{client_ip(request)}", DAY, PAYMENTS_PER_IP_DAY)
    payment_uuid = str(uuid_lib.uuid4())
    try:
        created = await urlpay.create(
            payment_uuid,
            amount,
            PAYMENT_DESCRIPTION,
            f"{settings.public_url}/pay/return",
            email,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("urlpay_create_error book=%s error=%s", book["id"], exc)
        raise HTTPException(status_code=502, detail="payment_failed") from None
    sbp = await urlpay.sbp_link(created.url)
    await asyncio.to_thread(
        db.add_payment,
        payment_uuid,
        book["id"],
        created.payment_id,
        amount,
        email,
        created.url,
        sbp,
        promo_code,
        offer["basePrice"],
    )
    log.info(
        "payment_created book=%s uuid=%s provider_id=%s amount=%s promo=%s sbp=%s",
        book["id"], payment_uuid, created.payment_id, amount, promo_code, bool(sbp),
    )
    track("payment_created", request, book, {"amount": amount, "promo": promo_code})
    payment = await asyncio.to_thread(db.payment, payment_uuid)
    return {"paid": False, "checkout": checkout(payment)}  # type: ignore[arg-type]


@app.get("/api/pay/current")
async def pay_current(request: Request) -> dict[str, Any]:
    book = require_book(request)
    if book["paid"]:
        return {"paid": True, "checkout": None}
    payment = await asyncio.to_thread(db.open_payment, book["id"], 60 * 60)
    return {"paid": False, "checkout": checkout(payment) if payment and payment.get("pay_url") else None}


@app.post("/api/pay/check")
async def pay_check(request: Request) -> dict[str, bool]:
    book = require_book(request)
    if book["paid"]:
        return {"paid": True}
    rate(f"paycheck:{book['id']}", 60, 30)
    for payment in await asyncio.to_thread(db.pending_payments, book["id"], 2 * DAY):
        if await check_payment(payment) == "paid":
            return {"paid": True}
    return {"paid": False}


@app.post("/webhook/urlpay")
async def urlpay_webhook(request: Request) -> Response:
    """Уведомление UrlPay. Телу не доверяем: берём uuid и перепроверяем платёж через API."""
    try:
        body = await request.json()
        payment_uuid = str(body.get("uuid") or "")[:64]
    except Exception:  # noqa: BLE001
        return Response("ok")
    payment = await asyncio.to_thread(db.payment, payment_uuid) if payment_uuid else None
    if payment and payment["status"] == "pending":
        await check_payment(payment)
    return Response("ok")


@app.get("/p/{code}")
async def promo_link(code: str, request: Request) -> Response:
    """Ссылка с промокодом: считаем переход, запоминаем код в cookie и ведём на главную."""
    normalized = normalize_code(code)
    promo = await asyncio.to_thread(db.promo, normalized) if normalized else None
    response = RedirectResponse("/#/", status_code=302)
    if promo and promo["active"]:
        unique = request.cookies.get(PROMO_COOKIE) != promo["code"]
        await asyncio.to_thread(db.promo_visit, promo["code"], unique)
        await asyncio.to_thread(track, "promo_visit", request, None, {"promo": promo["code"]})
        response.set_cookie(
            PROMO_COOKIE, promo["code"], max_age=30 * DAY, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/"
        )
    response.headers["X-Robots-Tag"] = "noindex"
    return response


@app.get("/pay/return")
async def pay_return() -> Response:
    return RedirectResponse("/#/paid", status_code=302)


# ---------- Админка ----------

if settings.admin_path and len(settings.admin_password) >= 12:
    app.include_router(
        admin_router(
            path=settings.admin_path,
            password=settings.admin_password,
            public_url=settings.public_url,
            db=db,
            default_price=settings.price_rub,
            secure=settings.cookie_secure,
            rate=rate,
            allow_ips=settings.admin_allow_ips,
        )
    )


# ---------- Сайт ----------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


ROOT_FILES = {
    "robots.txt",
    "sitemap.xml",
    "privacy.html",
    "terms.html",
    "favicon.svg",
    "favicon.ico",
    "apple-touch-icon.png",
    "og.png",
    "site.webmanifest",
}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(settings.web_dir / "index.html", media_type="text/html; charset=utf-8")


for folder in ("css", "js", "img"):
    if (settings.web_dir / folder).is_dir():
        app.mount(f"/{folder}", StaticFiles(directory=settings.web_dir / folder), name=folder)


@app.get("/{name}")
async def root_file(name: str) -> Response:
    if name in ROOT_FILES and (settings.web_dir / name).is_file():
        return FileResponse(settings.web_dir / name)
    return not_found_page()


def not_found_page() -> Response:
    page: Path = settings.web_dir / "404.html"
    return FileResponse(page, status_code=404, media_type="text/html; charset=utf-8")


@app.exception_handler(404)
async def not_found(request: Request, exc: Exception) -> Response:
    if request.url.path.startswith("/api/"):
        detail = getattr(exc, "detail", "not_found")
        return JSONResponse({"error": detail if detail != "Not Found" else "not_found"}, status_code=404)
    return not_found_page()


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> Response:
    if exc.status_code == 404 and not request.url.path.startswith("/api/"):
        return not_found_page()
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
