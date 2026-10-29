"""Цена полной книги: базовая (из админки или .env) и скидка по промокоду."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

PROMO_CODE = re.compile(r"^[A-Z0-9_-]{2,32}$")
PROMO_COOKIE = "ms_promo"
MIN_PRICE = Decimal("1.00")  # UrlPay не примет нулевой платёж


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_price(raw: str) -> str | None:
    try:
        value = Decimal(raw.replace(",", ".").replace(" ", ""))
    except (InvalidOperation, AttributeError):
        return None
    if value < MIN_PRICE or value > Decimal("1000000"):
        return None
    return money(value)


def base_price(db: Any, default: str) -> str:
    return db.setting("price_rub") or default


def discounted(base: str, percent: int) -> str:
    value = Decimal(base) * (Decimal(100) - Decimal(percent)) / Decimal(100)
    return money(max(value, MIN_PRICE))


def normalize_code(raw: str) -> str | None:
    code = (raw or "").strip().upper()
    return code if PROMO_CODE.match(code) else None


def active_promo(db: Any, cookie_value: str | None) -> dict[str, Any] | None:
    code = normalize_code(cookie_value or "")
    if not code:
        return None
    promo = db.promo(code)
    return promo if promo and promo["active"] else None


def quote(db: Any, default: str, cookie_value: str | None) -> dict[str, Any]:
    """Итоговая цена для покупателя с учётом промокода из cookie."""
    base = base_price(db, default)
    promo = active_promo(db, cookie_value)
    if promo is None:
        return {"price": base, "basePrice": base, "promo": None}
    return {
        "price": discounted(base, int(promo["percent"])),
        "basePrice": base,
        "promo": {"code": promo["code"], "percent": int(promo["percent"])},
    }
