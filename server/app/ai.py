"""Запросы к ИИ через OpenAI-совместимый API (как в доноре wgpt_bot).

Главное правило промптов из ТЗ: ИИ не выдумывает факты — только связывает и правит слова автора.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx

log = logging.getLogger("mystory.ai")


class AIBusy(Exception):
    """Все слоты заняты — просим повторить чуть позже."""


class AIError(Exception):
    pass


CHAPTER_SYSTEM = """Ты — бережный литературный редактор автобиографий.
Тебе дают ответы автора на вопросы одной главы его книги. Преврати их в связный текст главы от первого лица.

Строгие правила:
- Используй ТОЛЬКО факты из ответов. Не добавляй имена, даты, места, события, людей, чувства и детали, которых нет в ответах.
- Не делай выводов и оценок, которых автор сам не сделал: никаких «это было важно для меня», «это меня изменило», если он так не сказал. Не морализируй, не добавляй итогов в конце.
- Не пересказывай вопросы («Если бы мне пришлось описать себя…») — начинай сразу с сути ответа.
- Сохраняй голос автора: его слова, интонацию, характерные фразы. Исправляй только ошибки и повторы.
- Можно менять порядок, добавлять короткие связки между историями, объединять ответы в абзацы.
- Если ответов мало — текст получится коротким. Это нормально, не растягивай.
- Род автора: {gender}. Пиши на русском.
- Без заголовков, без markdown, без списков, без кавычек вокруг всего текста. Абзацы разделяй пустой строкой."""

FOLLOWUP_SYSTEM = """Ты помогаешь человеку вспомнить детали для автобиографии.
Тебе дают вопрос и ответ. Задай 1–2 коротких уточняющих вопроса, которые помогут раскрыть именно эту историю:
где и когда это было, кто был рядом, что предшествовало, какая деталь запомнилась, что человек чувствовал, чем всё закончилось, почему он это помнит, что думает сейчас.
Не спрашивай о том, что уже есть в ответе. Не предполагай фактов. Обращайся на «ты», род собеседника: {gender}.
Если ответ уже подробный и уточнять нечего — верни пустой список.
Ответь строго JSON: {{"questions": ["…", "…"]}}"""


class AIClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float, max_concurrent: int) -> None:
        self._url = f"{base_url}/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._model = model
        self._timeout = timeout
        self._slots = asyncio.Semaphore(max_concurrent)
        self._http = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._http.aclose()

    async def _complete(self, messages: list[dict[str, str]], max_tokens: int, json_mode: bool = False) -> str:
        if self._slots.locked():
            raise AIBusy()
        async with self._slots:
            payload: dict[str, object] = {
                "model": self._model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.4,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            for attempt in range(3):
                try:
                    resp = await self._http.post(self._url, headers=self._headers, json=payload)
                except httpx.HTTPError as exc:
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
                data = resp.json()
                content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                return content.strip()
            raise AIError("retries exhausted")

    async def chapter(self, title: str, pairs: list[tuple[str, str]], gender: str, author: str) -> str:
        gender_text = "женский" if gender == "f" else "мужской"
        blocks = "\n\n".join(f"Вопрос: {q}\nОтвет: {a}" for q, a in pairs)
        intro = f"Автор: {author}\n" if author else ""
        messages = [
            {"role": "system", "content": CHAPTER_SYSTEM.format(gender=gender_text)},
            {"role": "user", "content": f"{intro}Глава: «{title}»\n\n{blocks}"},
        ]
        text = await self._complete(messages, max_tokens=2200)
        return text.strip().strip("«»\"")

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
