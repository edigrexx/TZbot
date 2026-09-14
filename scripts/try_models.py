"""Прогон набора русских фраз через модели OpenRouter — чтобы выбрать модель на реальных данных.

    OPENROUTER_API_KEY=sk-or-... python scripts/try_models.py
    OPENROUTER_API_KEY=sk-or-... python scripts/try_models.py google/gemini-3.1-flash-lite openai/gpt-5.4-nano

Стоит центы: ~12 запросов на модель по ~1–1.5 тыс. токенов.
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

ZONES = parse_timezones("Almaty:Asia/Almaty,MSK:Europe/Moscow,Bishkek:Asia/Bishkek,Vietnam:Asia/Ho_Chi_Minh")
ALMATY = ZoneInfo("Asia/Almaty")
REF = datetime(2026, 9, 14, 10, 0, tzinfo=ALMATY)  # понедельник, 10:00 по Алматы

DEFAULT_CANDIDATES = [DEFAULT_MODEL, *DEFAULT_FALLBACK_MODELS, "openai/gpt-5.4-nano", "anthropic/claude-haiku-4.5"]


def at(day: int, hour: int, minute: int, tz: str = "Asia/Almaty", month: int = 9) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=ZoneInfo(tz))


# (текст, ожидаемый момент или None, ожидаемый approximate)
CASES: list[tuple[str, Optional[datetime], bool]] = [
    ("созвон в 15:00", at(14, 15, 0), False),
    ("давайте завтра в пол десятого", at(15, 9, 30), False),
    ("в 17:00 по Алматы", at(14, 17, 0), False),
    ("в среду в девять утра по мск", at(16, 9, 0, "Europe/Moscow"), False),
    ("завтра после обеда", at(15, 14, 0), True),
    ("в пятницу без четверти пять по Бишкеку", at(18, 16, 45, "Asia/Bishkek"), False),
    ("вьетнамцы предлагают в 8 вечера по их времени", at(14, 20, 0, "Asia/Ho_Chi_Minh"), False),
    ("через полтора часа", at(14, 11, 30), False),
    ("послезавтра в полдень", at(16, 12, 0), False),
    ("1 октября в 10:15 UTC", at(1, 10, 15, "UTC", month=10), False),
    ("в четверть третьего по Москве", at(14, 14, 15, "Europe/Moscow"), False),
    ("ок, договорились, скину ссылку", None, False),
]


async def run_model(api_key: str, model: str, effort: Optional[str]) -> None:
    extractor = OpenRouterExtractor(api_key, model, (), effort, ZONES)
    passed, latency, cost = 0, 0.0, 0.0
    print(f"\n=== {model}" + (f" (reasoning={effort})" if effort else ""))
    try:
        for text, expected, approximate in CASES:
            try:
                raw = await extractor(text, REF)
                got = parse_model_output(raw, REF)
                if expected is None:
                    ok = not got.found
                    shown = "не найдено" if not got.found else f"{got.moment:%Y-%m-%d %H:%M} {got.moment.tzinfo.key}"
                else:
                    ok = got.found and got.moment == expected and got.approximate == approximate
                    shown = (f"{got.moment:%Y-%m-%d %H:%M} {got.moment.tzinfo.key} approx={got.approximate}"
                             if got.found else "не найдено")
            except UserFacingError as error:
                ok, shown = False, f"ошибка: {error.message}"
            stats = extractor.last_stats
            if stats:
                latency += stats.latency
                cost += stats.cost or 0.0
            passed += ok
            timing = f"{stats.latency:4.1f}s" if stats else "  —  "
            print(f"  {'✓' if ok else '✗'} {timing}  {text!r:50} → {shown}")
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
