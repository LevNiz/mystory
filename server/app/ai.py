"""Запросы к ИИ через OpenAI-совместимый API (как в доноре wgpt_bot).

Главное правило промптов из ТЗ: ИИ не выдумывает факты — только связывает и правит слова автора.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx

log = logging.getLogger("mystory.ai")


class AIBusy(Exception):
    """Все слоты заняты — просим повторить чуть позже."""


class AIError(Exception):
    pass


CHAPTER_SYSTEM = """Ты — писатель-биограф. По материалам интервью ты пишешь главу автобиографии от первого лица.
Это должна быть глава книги, а не пересказ интервью: читатель не должен догадываться, что были вопросы.

Как писать:
- Не иди по порядку вопросов. Найди общую нить главы и выстрой текст по времени или по смыслу: одна история вытекает из другой.
- Начни со сцены, детали или образа из ответов — не с общих слов и не с «я родился», если глава не об этом.
- Никогда не повторяй формулировки вопросов и не используй обороты вроде «если говорить о…», «что касается…», «когда меня спрашивают…», «можно сказать, что…».
- Соединяй истории переходами — «тогда же», «спустя годы», «это я понял позже» — но только если связь есть в ответах.
- Передай характер автора: его интонацию, словечки, юмор, то, что для него важно. Для этого тебе дан портрет автора — опирайся на него, чтобы глава звучала его голосом.
- Пиши живым разговорным литературным языком, без канцелярита и пафоса. Предложения разной длины.

Жёсткие ограничения по фактам — важнее красоты текста:
- Разрешено: менять порядок, объединять ответы, добавлять короткие связки, править стиль, развернуть чувство или оценку, которую автор назвал сам.
- Запрещено добавлять любые новые конкретные детали: предметы, действия, жесты, погоду, обстановку, звуки, мысли, реплики, имена, даты, места, людей.
- Запрещено придумывать причины и следствия: если автор не сказал, что одно привело к другому, не связывай их причинно.
- Не делай выводов и оценок за автора, не добавляй морали и итогов в конце главы.
- Факты из портрета используй, только если они прямо относятся к теме главы; не пересказывай портрет.
- Не вычисляй возраст и годы, не уточняй то, что автор оставил неопределённым.
- Только русские слова, без вставок на других языках.
- Перед ответом проверь каждое предложение: есть ли его содержание в материалах? Если нет — убери или перепиши.

Объём: примерно как сумма ответов, не больше чем на треть длиннее. Если материала мало — короткая глава в 1–3 абзаца, без воды.
Род автора: {gender}. Язык — русский. Без заголовков, markdown, списков и кавычек вокруг текста. Абзацы разделяй пустой строкой."""

FOLLOWUP_SYSTEM = """Ты помогаешь человеку вспомнить детали для автобиографии.
Тебе дают вопрос и ответ. Задай 1–2 коротких уточняющих вопроса, которые помогут раскрыть именно эту историю:
где и когда это было, кто был рядом, что предшествовало, какая деталь запомнилась, что человек чувствовал, чем всё закончилось, почему он это помнит, что думает сейчас.
Не спрашивай о том, что уже есть в ответе. Не предполагай фактов. Обращайся на «ты», род собеседника: {gender}.
Если ответ уже подробный и уточнять нечего — верни пустой список.
Ответь строго JSON: {{"questions": ["…", "…"]}}"""


PHOTO_MARK = re.compile(r"^\[ФОТО(?:\s*(\d+))?\]$")
CAPTION_ECHO = re.compile(r"^[—–-]?\s*[«\"](.+?)[»\"]\s*$")


def place_photo_marks(text: str, count: int, captions: list[str] | None = None) -> str:
    """Ровно по одной метке [ФОТО n] на каждое фото главы, отдельными абзацами.

    Метки, которые ИИ поставил, сохраняем на своих местах; пропущенные распределяем
    равномерно по главе; лишние и повторы убираем.
    """
    raw = re.sub(r"\[ФОТО(?:\s*\d+)?\]", lambda m: f"\n\n{m.group(0)}\n\n", text)
    # ИИ иногда повторяет подпись рядом с меткой («— «Наша свадьба»») — такие строки убираем.
    known = {c.strip().lower() for c in captions or []}
    paragraphs = [
        p.strip()
        for p in raw.split("\n\n")
        if p.strip() and not ((m := CAPTION_ECHO.match(p.strip())) and m.group(1).strip().lower() in known)
    ]
    body: list[str] = []
    after: dict[int, int] = {}  # номер фото -> после скольких абзацев текста
    for p in paragraphs:
        match = PHOTO_MARK.match(p)
        if not match:
            body.append(p)
            continue
        number = int(match.group(1) or 1)
        if 1 <= number <= count and number not in after:
            after[number] = len(body)
    if not count or not body:
        return "\n\n".join(body)
    for number in range(1, count + 1):
        if number not in after:
            after[number] = max(1, round(len(body) * number / (count + 1)))
        after[number] = max(1, min(after[number], len(body)))
    out: list[str] = []
    for i, p in enumerate(body, start=1):
        out.append(p)
        out.extend(f"[ФОТО {n}]" for n in sorted(after, key=lambda k: (after[k], k)) if after[n] == i)
    return "\n\n".join(out)


class AIClient:
    def __init__(
        self, base_url: str, api_key: str, model: str, chapter_model: str, timeout: float, max_concurrent: int
    ) -> None:
        self._url = f"{base_url}/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._model = model
        # Главы пишет более сильная модель, уточняющие вопросы — быстрая и дешёвая.
        self._chapter_model = chapter_model or model
        self._timeout = timeout
        self._slots = asyncio.Semaphore(max_concurrent)
        self._http = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._http.aclose()

    async def _complete(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        json_mode: bool = False,
        model: str | None = None,
        temperature: float = 0.4,
    ) -> str:
        if self._slots.locked():
            raise AIBusy()
        async with self._slots:
            payload: dict[str, object] = {
                "model": model or self._model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            for attempt in range(3):
                try:
                    resp = await self._http.post(self._url, headers=self._headers, json=payload)
                except (httpx.HTTPError, OSError) as exc:  # OSError покрывает ssl.SSLError при обрыве TLS
                    log.warning("ai_http_error attempt=%s error=%s", attempt, exc)
                    await asyncio.sleep(1 + attempt)
                    continue
                if resp.status_code == 429 or resp.status_code >= 500:
                    log.warning("ai_retry status=%s attempt=%s", resp.status_code, attempt)
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                if not resp.is_success:
                    log.error("ai_failed status=%s body=%s", resp.status_code, resp.text[:300])
                    raise AIError(f"status {resp.status_code}")
                try:
                    data = resp.json()
                except ValueError:
                    log.warning("ai_bad_json attempt=%s", attempt)
                    await asyncio.sleep(1 + attempt)
                    continue
                content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                return content.strip()
            raise AIError("retries exhausted")

    async def chapter(
        self, title: str, pairs: list[tuple[str, str]], gender: str, portrait: str, photos: list[str] | None = None
    ) -> str:
        gender_text = "женский" if gender == "f" else "мужской"
        material = "\n\n".join(f"— {q}\n{a}" for q, a in pairs)
        photos = photos or []
        # Вёрстка: ИИ расставляет фотографии главы по смыслу подписей.
        layout = ""
        if photos:
            listed = "\n".join(f"[ФОТО {i}] — «{c}»" for i, c in enumerate(photos, start=1))
            layout = (
                f"\n\nК главе приложены фотографии:\n{listed}\n"
                "Поставь каждую метку отдельной строкой между абзацами — сразу после абзаца, к которому фото подходит по смыслу. "
                "Каждая метка ровно один раз, не перед первым абзацем, по возможности не две подряд. "
                "Строка с меткой содержит только саму метку, например [ФОТО 1] — без подписи и без тире. Подписи в текст не вставляй."
            )
        messages = [
            {"role": "system", "content": CHAPTER_SYSTEM.format(gender=gender_text)},
            {
                "role": "user",
                "content": (
                    f"Портрет автора (для голоса и связок):\n{portrait or 'нет данных'}\n\n"
                    f"Глава: «{title}»\n\nМатериалы интервью:\n\n{material}{layout}"
                ),
            },
        ]
        text = await self._complete(messages, max_tokens=6000, model=self._chapter_model, temperature=0.4)
        return place_photo_marks(text.strip().strip("«»\""), len(photos), photos)

    async def followups(self, question: str, answer: str, gender: str) -> list[str]:
        gender_text = "женский" if gender == "f" else "мужской"
        messages = [
            {"role": "system", "content": FOLLOWUP_SYSTEM.format(gender=gender_text)},
            {"role": "user", "content": f"Вопрос: {question}\nОтвет: {answer}"},
        ]
        raw = await self._complete(messages, max_tokens=220, json_mode=True)
        try:
            items = json.loads(raw).get("questions", [])
        except (json.JSONDecodeError, AttributeError):
            return []
        return [str(q).strip()[:200] for q in items if str(q).strip()][:2]
