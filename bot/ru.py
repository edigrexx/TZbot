"""Русские названия дат и форматирование смещений."""

from __future__ import annotations

from datetime import date, timedelta

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def format_date(d: date, with_year: bool = False) -> str:
    text = f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS_GENITIVE[d.month - 1]}"
    if with_year:
        text += f" {d.year}"
    return text[0].upper() + text[1:]


def format_day_shift(days: int) -> str:
    sign = "+" if days > 0 else "−"
    return f"{sign}{abs(days)} {plural(days, 'день', 'дня', 'дней')}"


def format_utc_offset(offset: timedelta) -> str:
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "−"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours}" + (f":{minutes:02d}" if minutes else "")
