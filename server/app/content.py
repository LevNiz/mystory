"""Вопросы читаем из того же файла, что и браузер (web/js/questions.js), — один источник правды."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_TEMPLATE = re.compile(r"\{([^|}]*)\|([^}]*)\}")


def gendered(text: str, gender: str) -> str:
    return _TEMPLATE.sub(lambda m: m.group(2) if gender == "f" else m.group(1), text)


@dataclass(frozen=True)
class Question:
    id: str
    title: str
    chapter_id: str  # глава полной книги, куда попадает ответ
    free: bool


@dataclass(frozen=True)
class Chapter:
    id: str
    title: str
    questions: tuple[Question, ...]


class Content:
    def __init__(self, questions_js: Path) -> None:
        raw = questions_js.read_text(encoding="utf-8")
        start = raw.index("{", raw.index("window.QUESTIONS"))
        body = raw[start : raw.rindex("}") + 1]
        data: dict[str, Any] = json.loads(body)

        self.questions: dict[str, Question] = {}
        free_qs: list[Question] = []
        for section in data["free"]:
            for q in section["questions"]:
                question = Question(q["id"], q["title"], q.get("into", section["id"]), True)
                free_qs.append(question)
                self.questions[question.id] = question

        # Бесплатная книга: 5 разделов. Полная: «Знакомство» + 10 глав, куда вливаются бесплатные ответы.
        self.free_chapters: dict[str, Chapter] = {
            s["id"]: Chapter(s["id"], s["title"], tuple(self.questions[q["id"]] for q in s["questions"]))
            for s in data["free"]
        }
        self.full_chapters: dict[str, Chapter] = {
            "intro": Chapter("intro", "Знакомство", tuple(q for q in free_qs if q.chapter_id == "intro")),
        }
        for c in data["full"]:
            own = []
            for q in c["questions"]:
                question = Question(q["id"], q["title"], c["id"], False)
                self.questions[question.id] = question
                own.append(question)
            merged = tuple(q for q in free_qs if q.chapter_id == c["id"]) + tuple(own)
            self.full_chapters[c["id"]] = Chapter(c["id"], c["title"], merged)

    def chapter(self, edition: str, chapter_id: str) -> Chapter | None:
        chapters = self.full_chapters if edition == "full" else self.free_chapters
        return chapters.get(chapter_id)
