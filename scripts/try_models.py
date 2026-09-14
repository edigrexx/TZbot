"""Прогон набора русских фраз через модели OpenRouter — чтобы выбрать модель на реальных данных.

    OPENROUTER_API_KEY=sk-or-... python scripts/try_models.py
    OPENROUTER_API_KEY=sk-or-... python scripts/try_models.py google/gemini-3.1-flash-lite openai/gpt-5.4-nano

Стоит центы: ~13 запросов на модель по ~1,5–2 тыс. токенов.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.config import DEFAULT_FALLBACK_MODELS, DEFAULT_MODEL, parse_timezones  # noqa: E402
from bot.extractor import OpenRouterExtractor  # noqa: E402
from bot.parsing import UserFacingError, parse_model_output  # noqa: E402

ZONES = parse_timezones("Almaty:Asia/Almaty,MSK:Europe/Moscow,Bishkek:Asia/Bishkek,Thailand:Asia/Bangkok,China:Asia/Shanghai")
REF = datetime(2026, 9, 14, 10, 0, tzinfo=ZoneInfo("Asia/Almaty"))  # понедельник, 10:00 по Алматы

DEFAULT_CANDIDATES = [DEFAULT_MODEL, *DEFAULT_FALLBACK_MODELS, "openai/gpt-5.4-nano", "anthropic/claude-haiku-4.5"]


def at(day: int, hour: int, minute: int, tz: str = "Asia/Almaty", month: int = 9) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=ZoneInfo(tz))


# (текст, ожидаемые встречи по порядку: (момент, approximate))
CASES: list[tuple[str, list[tuple[datetime, bool]]]] = [
    ("созвон в 15:00", [(at(14, 15, 0), False)]),
    ("давайте завтра в пол десятого", [(at(15, 9, 30), False)]),
    ("в 17 00 по Алматы", [(at(14, 17, 0), False)]),
    ("в среду в девять утра по мск", [(at(16, 9, 0, "Europe/Moscow"), False)]),
    ("завтра после обеда", [(at(15, 14, 0), True)]),
    ("в пятницу без четверти пять по Бишкеку", [(at(18, 16, 45, "Asia/Bishkek"), False)]),
    ("через полтора часа", [(at(14, 11, 30), False)]),
    ("послезавтра в полдень", [(at(16, 12, 0), False)]),
    ("1 октября в 10:15 UTC", [(at(1, 10, 15, "UTC", month=10), False)]),
    ("P2P (Overpay) — демо технического ядра согласовано на понедельник 12:00 МСК.",
     [(at(21, 12, 0, "Europe/Moscow"), False)]),
    (
        "План недели:\n• Демо P2P — вторник 12:00 МСК\n• Ретро спринта в четверг в 16 по Алматы\n"
        "• Созвон с партнёрами из Китая в пятницу в 10 утра по Пекину",
        [(at(15, 12, 0, "Europe/Moscow"), False), (at(17, 16, 0), False), (at(18, 10, 0, "Asia/Shanghai"), False)],
    ),
    ("ок, договорились, скину ссылку", []),
]


def describe(meeting) -> str:
    title = f"«{meeting.title}» " if meeting.title else ""
    return f"{title}{meeting.moment:%Y-%m-%d %H:%M} {meeting.moment.tzinfo.key}" + (" ≈" if meeting.approximate else "")


async def run_model(api_key: str, model: str, effort: Optional[str]) -> None:
    extractor = OpenRouterExtractor(api_key, model, (), effort, ZONES)
    passed, latency, cost = 0, 0.0, 0.0
    print(f"\n=== {model}" + (f" (reasoning={effort})" if effort else ""))
    try:
        for text, expected in CASES:
            try:
                raw = await extractor(text, REF)
                got = parse_model_output(raw, REF)
                ok = len(got.meetings) == len(expected) and not got.errors and all(
                    m.moment == moment and m.approximate == approximate
                    for m, (moment, approximate) in zip(got.meetings, expected)
                )
                shown = "; ".join(describe(m) for m in got.meetings) or "не найдено"
                if got.errors:
                    shown += f" | ошибки: {'; '.join(got.errors)}"
            except UserFacingError as error:
                ok, shown = False, f"ошибка: {error.message}"
            stats = extractor.last_stats
            if stats:
                latency += stats.latency
                cost += stats.cost or 0.0
            passed += ok
            timing = f"{stats.latency:4.1f}s" if stats else "  —  "
            print(f"  {'✓' if ok else '✗'} {timing}  {text.splitlines()[0][:45]!r:48} → {shown}")
    finally:
        await extractor.close()
    print(f"  итого {passed}/{len(CASES)}, в среднем {latency / len(CASES):.2f}s, стоимость ${cost:.5f}")


async def main() -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        sys.exit("Задайте OPENROUTER_API_KEY")
    effort = os.environ.get("OPENROUTER_REASONING_EFFORT") or None
    for model in sys.argv[1:] or DEFAULT_CANDIDATES:
        await run_model(api_key, model, effort)


if __name__ == "__main__":
    asyncio.run(main())
