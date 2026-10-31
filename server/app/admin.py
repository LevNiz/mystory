"""Админка на скрытом адресе: цена полной книги, промокоды и статистика.

Адрес и пароль задаются в .env (ADMIN_PATH, ADMIN_PASSWORD). Без них админка выключена.
Сессия — подписанная cookie (HMAC), только для пути админки, SameSite=Strict;
POST-запросы дополнительно проверяют Origin.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import secrets
import string
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .pricing import base_price, discounted, normalize_code, parse_price

SESSION_COOKIE = "ms_admin"
SESSION_TTL = 7 * 86_400
MSK = timezone(timedelta(hours=3))


def build_router(
    *, path: str, password: str, public_url: str, db: Any, default_price: str, secure: bool, rate: Callable[..., None]
) -> APIRouter:
    base = "/" + path.strip("/")
    secret = hashlib.sha256(f"mystory-admin:{password}:{path}".encode()).digest()
    router = APIRouter()

    def sign(expires: int) -> str:
        mac = hmac.new(secret, str(expires).encode(), hashlib.sha256).hexdigest()
        return f"{expires}.{mac}"

    def authed(request: Request) -> bool:
        raw = request.cookies.get(SESSION_COOKIE, "")
        expires, _, mac = raw.partition(".")
        if not expires.isdigit() or int(expires) < time.time():
            return False
        return hmac.compare_digest(sign(int(expires)), raw)

    def same_origin(request: Request) -> bool:
        origin = request.headers.get("origin") or request.headers.get("referer") or ""
        allowed = {urlparse(public_url).netloc, request.headers.get("host", "")}
        return urlparse(origin).netloc in allowed

    def back(note: str = "") -> RedirectResponse:
        return RedirectResponse(f"{base}?msg={note}" if note else base, status_code=303)

    def ip(request: Request) -> str:
        return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")

    @router.get(base)
    async def page(request: Request) -> Response:
        if not authed(request):
            return HTMLResponse(login_page(base, request.query_params.get("msg", "")), headers=NO_INDEX)
        data = await asyncio.to_thread(collect, db, default_price)
        return HTMLResponse(dashboard(base, public_url, data, request.query_params.get("msg", "")), headers=NO_INDEX)

    @router.post(f"{base}/login")
    async def login(request: Request) -> Response:
        if not same_origin(request):
            return back()
        rate(f"admin-login:{ip(request)}", 3600, 10)
        form = await request.form()
        if not hmac.compare_digest(str(form.get("password", "")).encode(), password.encode()):
            await asyncio.sleep(1)
            return back("wrong")
        response = back()
        response.set_cookie(
            SESSION_COOKIE, sign(int(time.time()) + SESSION_TTL), max_age=SESSION_TTL,
            httponly=True, secure=secure, samesite="strict", path=base,
        )
        return response

    @router.post(f"{base}/logout")
    async def logout() -> Response:
        response = back()
        response.delete_cookie(SESSION_COOKIE, path=base)
        return response

    @router.post(f"{base}/price")
    async def set_price(request: Request) -> Response:
        if not authed(request) or not same_origin(request):
            return back()
        form = await request.form()
        price = parse_price(str(form.get("price", "")))
        if price is None:
            return back("bad_price")
        await asyncio.to_thread(db.set_setting, "price_rub", price)
        return back("price_saved")

    @router.post(f"{base}/full-free")
    async def set_full_free(request: Request) -> Response:
        if not authed(request) or not same_origin(request):
            return back()
        form = await request.form()
        enabled = form.get("enabled") == "1"
        await asyncio.to_thread(db.set_setting, "full_free", "1" if enabled else "0")
        return back("free_on" if enabled else "free_off")

    @router.post(f"{base}/promo")
    async def add_promo(request: Request) -> Response:
        if not authed(request) or not same_origin(request):
            return back()
        form = await request.form()
        raw_code = str(form.get("code", "")).strip()
        code = normalize_code(raw_code) if raw_code else random_code()
        percent = to_percent(form.get("percent"))
        if code is None or percent is None:
            return back("bad_promo")
        ok = await asyncio.to_thread(db.add_promo, code, percent, str(form.get("note", ""))[:120])
        return back("promo_added" if ok else "promo_exists")

    @router.post(f"{base}/promo/{{code}}")
    async def edit_promo(code: str, request: Request) -> Response:
        if not authed(request) or not same_origin(request):
            return back()
        form = await request.form()
        normalized = normalize_code(code)
        percent = to_percent(form.get("percent"))
        if normalized is None or percent is None:
            return back("bad_promo")
        await asyncio.to_thread(
            db.update_promo, normalized, percent, form.get("active") == "1", str(form.get("note", ""))[:120]
        )
        return back("promo_saved")

    return router


NO_INDEX = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def random_code() -> str:
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))


def to_percent(raw: Any) -> int | None:
    try:
        value = int(str(raw).strip())
    except ValueError:
        return None
    return value if 1 <= value <= 99 else None


def collect(db: Any, default_price: str) -> dict[str, Any]:
    return {
        "price": base_price(db, default_price),
        "price_from_env": db.setting("price_rub") is None,
        "full_free": db.setting("full_free") == "1",
        "promos": db.promos_with_stats(),
        "payments": db.recent_payments(30),
        "totals": db.totals(),
    }


# ---------- Разметка ----------

MESSAGES = {
    "wrong": ("err", "Неверный пароль"),
    "price_saved": ("ok", "Цена сохранена — уже действует на сайте"),
    "free_on": ("ok", "Полная книга теперь бесплатна для всех"),
    "free_off": ("ok", "Бесплатный доступ выключен — полная книга снова платная"),
    "bad_price": ("err", "Цена должна быть числом от 1 ₽"),
    "promo_added": ("ok", "Промокод создан"),
    "promo_saved": ("ok", "Промокод сохранён"),
    "promo_exists": ("err", "Такой промокод уже есть"),
    "bad_promo": ("err", "Код — латиница, цифры, «-» и «_», 2–32 символа; скидка — от 1 до 99 %"),
}

STATUS = {"paid": "оплачен", "pending": "ожидает", "failed": "не оплачен", "mismatch": "не совпал"}

CSS = """
*{box-sizing:border-box}body{margin:0;background:#f8f7f4;color:#16171b;font:15px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
header{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:20px}
h1{font-size:22px;margin:0}h2{font-size:17px;margin:0 0 14px}
.card{background:#fff;border:1px solid #e8e6e1;border-radius:16px;padding:20px;margin-bottom:16px;overflow-x:auto}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.stats div{background:#fff;border:1px solid #e8e6e1;border-radius:14px;padding:14px 16px}
.stats b{display:block;font-size:22px}.stats span{color:#8a8c93;font-size:13px}
form.inline{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
input,button{font:inherit}input[type=text],input[type=number],input[type=password]{height:38px;padding:0 12px;border:1px solid #d9d6cf;border-radius:10px;background:#fff}
input[type=number]{width:96px}
button{height:38px;padding:0 16px;border:0;border-radius:999px;background:#16171b;color:#fff;cursor:pointer}
button.ghost{background:#fff;color:#16171b;border:1px solid #d9d6cf}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:9px 8px;border-top:1px solid #eeece7;vertical-align:middle;white-space:nowrap}
th{color:#8a8c93;font-weight:500;border-top:0}
.code{font-weight:600;font-family:ui-monospace,Menlo,monospace}.muted{color:#8a8c93}
.link{font-family:ui-monospace,Menlo,monospace;font-size:13px;user-select:all}
.msg{padding:10px 14px;border-radius:10px;margin-bottom:16px}.ok{background:#e6f6ee;color:#1f6f49}.err{background:#fdecea;color:#a1301d}
.off{opacity:.5}.free-on{border-color:#2f9e6a;background:#f3fbf7}.tag{padding:2px 8px;border-radius:99px;font-size:12px;background:#f0efea}.tag.paid{background:#e6f6ee;color:#1f6f49}
.login{max-width:360px;margin:15vh auto;display:flex;flex-direction:column;gap:12px}
@media(max-width:700px){.stats{grid-template-columns:repeat(2,1fr)}}
"""


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def rub(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return esc(value)
    text = f"{number:,.2f}".replace(",", " ").replace(".00", "")
    return f"{text} ₽"


def when(ts: int) -> str:
    return datetime.fromtimestamp(ts, MSK).strftime("%d.%m %H:%M")


def mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "—"
    name, _, domain = email.partition("@")
    return f"{name[:2]}***@{domain}"


def shell(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow">
<title>{esc(title)}</title><style>{CSS}</style></head><body>{body}</body></html>"""


def notice(code: str) -> str:
    if code not in MESSAGES:
        return ""
    kind, text = MESSAGES[code]
    return f'<div class="msg {kind}">{esc(text)}</div>'


def login_page(base: str, msg: str) -> str:
    return shell(
        "Вход",
        f"""<form class="login card" method="post" action="{base}/login">
        <h1>Админка</h1>{notice(msg)}
        <input type="password" name="password" placeholder="Пароль" autocomplete="current-password" required autofocus>
        <button type="submit">Войти</button></form>""",
    )


def dashboard(base: str, public_url: str, data: dict[str, Any], msg: str) -> str:
    totals = data["totals"]
    price = data["price"]
    promo_rows = "".join(promo_row(base, public_url, p, price) for p in data["promos"]) or (
        '<tr><td colspan="9" class="muted">Промокодов пока нет</td></tr>'
    )
    payment_rows = "".join(
        f"""<tr><td>{when(p["created_at"])}</td><td>{rub(p["amount"])}</td>
        <td>{esc(p.get("promo") or "—")}</td><td><span class="tag {esc(p["status"])}">{STATUS.get(p["status"], esc(p["status"]))}</span></td>
        <td class="muted">{esc(mask(p.get("email")))}</td><td class="muted">№ {esc(p.get("provider_id"))}</td></tr>"""
        for p in data["payments"]
    ) or '<tr><td colspan="6" class="muted">Платежей пока нет</td></tr>'

    return shell(
        "Админка — Книга моей жизни",
        f"""<div class="wrap">
<header><h1>Книга моей жизни · админка</h1>
<form method="post" action="{base}/logout"><button class="ghost" type="submit">Выйти</button></form></header>
{notice(msg)}
<div class="stats">
  <div><b>{totals["paid"]}</b><span>оплат</span></div>
  <div><b>{rub(totals["revenue"])}</b><span>выручка</span></div>
  <div><b>{totals["books"]}</b><span>книг начато</span></div>
  <div><b>{'0 ₽' if data['full_free'] else rub(price)}</b><span>{'сейчас бесплатно' if data['full_free'] else 'цена полной книги'}</span></div>
</div>
<br>
<section class="card"><h2>Цена полной книги</h2>
<form class="inline" method="post" action="{base}/price">
  <input type="text" name="price" value="{esc(price)}" inputmode="decimal" required> <span>₽</span>
  <button type="submit">Сохранить</button>
  <span class="muted">{"Сейчас берётся из .env (PRICE_RUB)" if data["price_from_env"] else "Задана здесь, перекрывает .env"}</span>
</form></section>

<section class="card {'free-on' if data['full_free'] else ''}"><h2>Полная книга бесплатно</h2>
<form class="inline" method="post" action="{base}/full-free">
  <input type="hidden" name="enabled" value="{'0' if data['full_free'] else '1'}">
  <span class="tag {'paid' if data['full_free'] else ''}">{'Включено: полная книга открыта всем' if data['full_free'] else 'Выключено: полная книга платная'}</span>
  <button type="submit" class="{'ghost' if data['full_free'] else ''}">{'Выключить' if data['full_free'] else 'Включить бесплатно'}</button>
</form>
<p class="muted">Пока режим включён, оплата не нужна: все главы, фото, посвящение и PDF открыты каждому. Уже оплатившие ничего не теряют.</p>
</section>

<section class="card"><h2>Промокоды</h2>
<form class="inline" method="post" action="{base}/promo">
  <input type="text" name="code" placeholder="КОД (пусто — случайный)" maxlength="32">
  <input type="number" name="percent" min="1" max="99" placeholder="%" required>
  <input type="text" name="note" placeholder="Заметка: канал, блогер…" maxlength="120">
  <button type="submit">Создать</button>
</form><br>
<table><thead><tr><th>Код</th><th>Скидка</th><th>Цена</th><th>Ссылка</th><th>Переходы</th><th>Уник.</th><th>Счета</th><th>Оплаты</th><th>Выручка</th></tr></thead>
<tbody>{promo_rows}</tbody></table>
<p class="muted">Переходы — открытия ссылки, уникальные — по браузерам. Счета — сколько раз нажали «Оплатить» с этим кодом.</p>
</section>

<section class="card"><h2>Последние платежи</h2>
<table><thead><tr><th>Когда (МСК)</th><th>Сумма</th><th>Промокод</th><th>Статус</th><th>E-mail</th><th>UrlPay</th></tr></thead>
<tbody>{payment_rows}</tbody></table></section>
</div>""",
    )


def promo_row(base: str, public_url: str, p: dict[str, Any], price: str) -> str:
    code = esc(p["code"])
    link = f"{public_url}/p/{p['code']}"
    conversion = f"{p['paid'] / p['uniques'] * 100:.0f} %" if p["uniques"] else "—"
    return f"""<tr class="{'' if p['active'] else 'off'}">
<td><span class="code">{code}</span><br><span class="muted">{esc(p['note'])}</span></td>
<td colspan="1"><form class="inline" method="post" action="{base}/promo/{code}">
  <input type="number" name="percent" min="1" max="99" value="{p['percent']}"> %
  <input type="hidden" name="note" value="{esc(p['note'])}">
  <label><input type="checkbox" name="active" value="1" {'checked' if p['active'] else ''}> вкл</label>
  <button class="ghost" type="submit">OK</button></form></td>
<td>{rub(discounted(price, int(p['percent'])))}</td>
<td><span class="link">{esc(link)}</span></td>
<td>{p['visits']}</td><td>{p['uniques']}</td><td>{p['checkouts']}</td>
<td><b>{p['paid']}</b> <span class="muted">({conversion})</span></td><td>{rub(p['revenue'])}</td></tr>"""
