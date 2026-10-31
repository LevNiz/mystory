"""Настройки из переменных окружения. Секреты живут только в .env на сервере."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _codes(name: str, default: str) -> frozenset[str]:
    return frozenset(x.strip() for x in (_env(name) or default).split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
    public_url: str
    web_dir: Path
    db_path: Path
    cookie_secure: bool

    ai_base_url: str
    ai_api_key: str
    ai_model: str
    ai_chapter_model: str
    ai_timeout: float
    ai_max_concurrent: int

    urlpay_api_key: str
    urlpay_secret_key: str
    urlpay_shop_id: int
    price_rub: str
    urlpay_paid_statuses: frozenset[str]
    urlpay_failed_statuses: frozenset[str]

    admin_path: str
    admin_password: str
    admin_allow_ips: frozenset[str]

    @property
    def ai_enabled(self) -> bool:
        return bool(self.ai_base_url and self.ai_api_key)

    @property
    def payments_enabled(self) -> bool:
        # Без кода «оплачено» не берём деньги: подтвердить платёж было бы нечем.
        return bool(self.urlpay_api_key and self.urlpay_secret_key and self.urlpay_shop_id and self.urlpay_paid_statuses)


def load_settings() -> Settings:
    root = Path(__file__).resolve().parents[2]
    return Settings(
        public_url=_env("PUBLIC_URL", "http://localhost:8000").rstrip("/"),
        web_dir=Path(_env("WEB_DIR", str(root / "web"))),
        db_path=Path(_env("DB_PATH", str(root / "data" / "mystory.db"))),
        cookie_secure=_env("COOKIE_SECURE", "1") != "0",
        # Модель для книги можно задать отдельно от донора: MYSTORY_AI_MODEL.
        ai_base_url=_env("AI_BASE_URL").rstrip("/"),
        ai_api_key=_env("AI_API_KEY"),
        ai_model=_env("MYSTORY_AI_MODEL") or _env("AI_MODEL", "gpt-4o-mini"),
        # Главы книги — отдельная, более сильная модель (литературный текст).
        ai_chapter_model=_env("MYSTORY_AI_CHAPTER_MODEL", "claude-sonnet-4-6"),
        ai_timeout=float(_env("AI_TIMEOUT_SECONDS", "90") or 90),
        ai_max_concurrent=int(_env("AI_MAX_CONCURRENT", "4") or 4),
        urlpay_api_key=_env("URLPAY_API_KEY"),
        urlpay_secret_key=_env("URLPAY_SECRET_KEY"),
        urlpay_shop_id=int(_env("URLPAY_SHOP_ID", "0") or 0),
        price_rub=_env("PRICE_RUB", "1490.00"),
        # Коды поля status из спецификации UrlPay: 0 создан, 1 в обработке, 2 отменён,
        # 3 обработан (оплачен), 4 ошибка, 5–6 холд.
        urlpay_paid_statuses=_codes("URLPAY_PAID_STATUSES", "3"),
        urlpay_failed_statuses=_codes("URLPAY_FAILED_STATUSES", "2,4"),
        # Админка: скрытый адрес и пароль. Пустые — админка выключена.
        admin_path=_env("ADMIN_PATH").strip("/"),
        admin_password=_env("ADMIN_PASSWORD"),
        # Необязательный список IP, с которых пускать в админку (через запятую). Пусто — откуда угодно.
        admin_allow_ips=frozenset(x.strip() for x in _env("ADMIN_ALLOW_IPS").split(",") if x.strip()),
    )
