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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .ai import AIBusy, AIClient, AIError
from .config import load_settings
from .content import Content, gendered
from .db import Database
from .urlpay import UrlPay, verdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("mystory")

settings = load_settings()
db = Database(settings.db_path)
content = Content(settings.web_dir / "js" / "questions.js")
urlpay = (
    UrlPay(settings.urlpay_api_key, settings.urlpay_secret_key, settings.urlpay_shop_id)
    if settings.payments_enabled
    else None
)
ai: AIClient | None = None

COOKIE = "ms_book"
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
PAYMENTS_PER_BOOK_HOUR = 10

PAYMENT_DESCRIPTION = "Полная книга моей жизни"
CHAPTER_ID = re.compile(r"^[a-z]{2,12}$")
QUESTION_ID = re.compile(r"^[a-z0-9-]{2,20}$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global ai
    if settings.ai_enabled:
        ai = AIClient(
            settings.ai_base_url,
            settings.ai_api_key,
            settings.ai_model,
            settings.ai_timeout,
            settings.ai_max_concurrent,
        )
    log.info("start ai=%s payments=%s", bool(ai), bool(urlpay))
    yield
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
    if path.startswith("/api/") and request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        # Защита от CSRF: кросс-сайтовая форма не может выставить этот заголовок.
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
    if settings.cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

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


def current_book(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 100:
        return None
    return db.book_by_token(token_hash(token))


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
        return {"exists": False, "paid": False, "data": None, "ai": {}, "photos": {}}
    return {
        "exists": True,
        "paid": book["paid"],
        "data": book["data"],
        "ai": book["ai"],
        "photos": db.photos(book["id"]),
    }


def features() -> dict[str, Any]:
    return {"ai": bool(ai), "payments": bool(urlpay), "price": settings.price_rub}


# ---------- Книга ----------


@app.get("/api/state")
async def get_state(request: Request) -> dict[str, Any]:
    book = await asyncio.to_thread(current_book, request)
    return {**public_state(book), "features": features()}


@app.put("/api/state")
async def put_state(request: Request) -> Response:
    body = await read_json(request)
    data = body.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="bad_data")
    data.pop("paid", None)  # статус оплаты знает только сервер

    book = await asyncio.to_thread(current_book, request)
    response = JSONResponse({"ok": True})
    if book is None:
        rate(f"books:{client_ip(request)}", 3600, BOOKS_PER_IP_HOUR)
        token = secrets.token_urlsafe(32)
        book_id = str(uuid_lib.uuid4())
        await asyncio.to_thread(db.create_book, book_id, token_hash(token))
        set_cookie(response, token)
    else:
        book_id = book["id"]
    await asyncio.to_thread(db.save_data, book_id, data)
    return response


@app.put("/api/photo/{chapter_id}")
async def put_photo(chapter_id: str, request: Request) -> dict[str, bool]:
    book = require_book(request)
    if not book["paid"]:
        raise HTTPException(status_code=402, detail="paid_only")
    if chapter_id not in content.full_chapters:
        raise HTTPException(status_code=404, detail="unknown_chapter")
    body = await read_json(request)
    caption = str(body.get("caption") or "")[:200]
    src = body.get("src")
    if src is not None:
        if not isinstance(src, str) or not re.match(r"^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$", src):
            raise HTTPException(status_code=400, detail="bad_image")
        if len(src) > MAX_PHOTO_BYTES:
            raise HTTPException(status_code=413, detail="too_large")
    await asyncio.to_thread(db.put_photo, book["id"], chapter_id, src, caption)
    return {"ok": True}


@app.delete("/api/photo/{chapter_id}")
async def delete_photo(chapter_id: str, request: Request) -> dict[str, bool]:
    book = require_book(request)
    await asyncio.to_thread(db.delete_photo, book["id"], chapter_id[:20])
    return {"ok": True}


@app.get("/api/recovery-link")
async def recovery_link(request: Request) -> dict[str, str]:
    require_book(request)
    return {"url": f"{settings.public_url}/r/{request.cookies[COOKIE]}"}


@app.get("/r/{token}")
async def recover(token: str) -> Response:
    if len(token) > 100 or db.book_by_token(token_hash(token)) is None:
        return RedirectResponse("/#/", status_code=302)
    response = RedirectResponse("/#/book", status_code=302)
    set_cookie(response, token)
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
    source = hashlib.sha256(json.dumps([pairs, gender], ensure_ascii=False).encode()).hexdigest()[:16]
    key = f"{edition}:{chapter_id}"

    cached = book["ai"].get(key)
    if cached and cached.get("source") == source and not body.get("force"):
        return cached

    ai_quota(book, "chapter", request)
    author = str((book["data"].get("profile") or {}).get("name") or "")[:80]
    try:
        text = await ai.chapter(title, pairs, gender, author)  # type: ignore[union-attr]
    except AIBusy:
        raise HTTPException(status_code=503, detail="ai_busy") from None
    except AIError:
        raise HTTPException(status_code=502, detail="ai_failed") from None
    if not text:
        raise HTTPException(status_code=502, detail="ai_empty")

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
    result = verdict(remote, payment["uuid"], int(payment["provider_id"]), payment["amount"])
    log.info(
        "urlpay_check uuid=%s result=%s status_fields=%s",
        payment["uuid"],
        result,
        {k: remote.get(k) for k in ("status", "payment_status", "state") if k in remote},
    )
    if result == "paid":
        await asyncio.to_thread(db.set_payment_status, payment["uuid"], "paid")
        await asyncio.to_thread(db.mark_paid, payment["book_id"])
    elif result in {"failed", "mismatch"}:
        await asyncio.to_thread(db.set_payment_status, payment["uuid"], result)
    return result


@app.post("/api/pay")
async def pay(request: Request) -> dict[str, Any]:
    book = require_book(request)
    if book["paid"]:
        return {"paid": True}
    if urlpay is None:
        raise HTTPException(status_code=503, detail="payments_disabled")
    rate(f"pay:{book['id']}", 3600, PAYMENTS_PER_BOOK_HOUR)
    payment_uuid = str(uuid_lib.uuid4())
    try:
        created = await urlpay.create(
            payment_uuid,
            settings.price_rub,
            PAYMENT_DESCRIPTION,
            f"{settings.public_url}/pay/return",
        )
    except Exception as exc:  # noqa: BLE001
        log.error("urlpay_create_error book=%s error=%s", book["id"], exc)
        raise HTTPException(status_code=502, detail="payment_failed") from None
    await asyncio.to_thread(db.add_payment, payment_uuid, book["id"], created.payment_id, settings.price_rub)
    log.info("payment_created book=%s uuid=%s provider_id=%s", book["id"], payment_uuid, created.payment_id)
    return {"paid": False, "url": created.url}


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


@app.get("/pay/return")
async def pay_return() -> Response:
    return RedirectResponse("/#/paid", status_code=302)


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
