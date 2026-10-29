"""UrlPay — по образцу клиента из wgpt_bot, но только разовый платёж.

Подтверждение оплаты всегда берём из API UrlPay (GET платежа), а не из тела входящего уведомления:
уведомления не подписаны, и подделать их может кто угодно.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

log = logging.getLogger("mystory.urlpay")

URLPAY_BASE = "https://urlpay.io/api"

# Значения статуса, которые считаем успешной оплатой. UrlPay в уведомлениях шлёт "success".
PAID_STATUSES = {"success", "succeeded", "paid", "completed", "complete", "done"}
FAILED_STATUSES = {"cancel", "canceled", "cancelled", "fail", "failed", "error", "expired", "rejected"}


@dataclass
class Created:
    payment_id: int
    url: str


class UrlPay:
    def __init__(self, api_key: str, secret_key: str, shop_id: int) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._shop_id = shop_id

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _sign(self, currency: str, amount: str) -> str:
        raw = f"{currency}{amount}{self._shop_id}{self._secret_key}"
        return hashlib.sha1(raw.encode()).hexdigest()

    async def create(self, uuid: str, amount: str, description: str, website_url: str) -> Created:
        currency = "rub"
        payload: dict[str, object] = {
            "currency": currency,
            "amount": amount,
            "uuid": uuid,
            "shopId": self._shop_id,
            "description": description,
            "website_url": website_url,
            "language": "ru",
            "items": [
                {
                    "description": description,
                    "quantity": 1,
                    "price": float(amount),
                    "vat_code": 1,
                    "payment_subject": 1,
                    "payment_mode": 1,
                }
            ],
            "sign": self._sign(currency, amount),
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{URLPAY_BASE}/v2/payments", headers=self._headers(), json=payload)
        if not resp.is_success:
            log.error("urlpay_create_failed status=%s body=%s", resp.status_code, resp.text[:300])
            resp.raise_for_status()
        data = resp.json()
        payment_id = int(data.get("id") or 0)
        url = str(data.get("paymentUrl") or "")
        if not data.get("success") or payment_id <= 0 or not url.startswith("https://"):
            raise RuntimeError("urlpay_invalid_response")
        return Created(payment_id=payment_id, url=url)

    async def get(self, payment_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{URLPAY_BASE}/v2/payments/{payment_id}", headers=self._headers())
        resp.raise_for_status()
        data = resp.json()
        payment = data.get("payment") if isinstance(data, dict) else None
        if not isinstance(payment, dict):
            raise RuntimeError("urlpay_invalid_payment")
        return payment


def verdict(
    payment: dict[str, Any],
    uuid: str,
    payment_id: int,
    amount: str,
    paid_codes: frozenset[str] = frozenset(),
    failed_codes: frozenset[str] = frozenset(),
) -> str:
    """'paid' | 'failed' | 'pending' | 'mismatch' по данным самого UrlPay.

    Наш uuid UrlPay хранит в `external_id` (в `uuid` — их собственный). Статус в API числовой:
    3 — обработан (оплачен), 2 — отменён, 4 — ошибка (см. настройки URLPAY_*_STATUSES).
    """
    our_id = str(payment.get("external_id") or payment.get("uuid") or "")
    if our_id != uuid or int(payment.get("id") or 0) != payment_id:
        return "mismatch"
    try:
        if Decimal(str(payment.get("amount"))).quantize(Decimal("0.01")) != Decimal(amount).quantize(Decimal("0.01")):
            return "mismatch"
    except (InvalidOperation, TypeError):
        return "mismatch"
    status = ""
    for key in ("payment_status", "status", "state"):
        if payment.get(key) not in (None, ""):
            status = str(payment[key]).strip().lower()
            break
    if status in paid_codes or (not status.isdigit() and status in PAID_STATUSES):
        return "paid"
    if status in failed_codes or (not status.isdigit() and status in FAILED_STATUSES):
        return "failed"
    return "pending"
