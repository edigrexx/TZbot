"""Пересчёт между зонами (только zoneinfo) и форматирование ответа."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Sequence

from .config import Zone
from .parsing import MAX_MEETINGS, Extraction, Meeting
from .ru import WEEKDAYS_SHORT, format_date, format_day_shift, format_utc_offset, plural

TELEGRAM_MESSAGE_LIMIT = 4096
_RELATIVE_DAYS = {-1: "вчера", 0: "сегодня", 1: "завтра", 2: "послезавтра"}


@dataclass(frozen=True)
class Row:
    label: str
    local: datetime
    day_shift: int  # разница календарных дат относительно исходной зоны


def convert(moment: datetime, zones: Sequence[Zone]) -> list[Row]:
    source_date = moment.date()
    rows = []
    for zone in zones:
        local = moment.astimezone(zone.tz)
        rows.append(Row(zone.label, local, (local.date() - source_date).days))
    # sorted стабилен: при равном смещении сохраняется порядок из TIMEZONES.
    return sorted(rows, key=lambda row: row.local.utcoffset())


def source_label(zones: Sequence[Zone], tz_key: str) -> str:
    for zone in zones:
        if zone.tz.key == tz_key:
            return zone.label
    return tz_key


def _when(moment: datetime, now: datetime) -> str:
    text = format_date(moment.date(), with_year=moment.year != now.year)
    relative = _RELATIVE_DAYS.get((moment.date() - now.astimezone(moment.tzinfo).date()).days)
    if relative:
        text += f" ({relative})"
    return f"{text}, {moment:%H:%M}"


def _table(moment: datetime, zones: Sequence[Zone]) -> str:
    rows = convert(moment, zones)
    width = max(len(row.label) for row in rows)
    lines = []
    for row in rows:
        line = f"{row.label.ljust(width)}  {row.local:%H:%M}  {format_utc_offset(row.local.utcoffset()):<8}"
        if row.day_shift:
            weekday = WEEKDAYS_SHORT[row.local.weekday()]
            line += f"  {format_day_shift(row.day_shift)}, {weekday} {row.local:%d.%m}"
        lines.append(line.rstrip())
    return "<pre>" + escape("\n".join(lines)) + "</pre>"


def format_meeting(meeting: Meeting, zones: Sequence[Zone], now: datetime) -> str:
    moment = meeting.moment
    label = escape(source_label(zones, moment.tzinfo.key))  # type: ignore[union-attr]
    when = escape(_when(moment, now))
    if meeting.title:
        header = f"📅 <b>{escape(meeting.title)}</b>\n{when} ({label})"
    else:
        header = f"📅 <b>{when}</b> ({label})"

    lines = [header, _table(moment, zones)]
    if not meeting.tz_explicit:
        lines.append(f"ℹ️ Пояс в сообщении не назван — считаю по {label}.")
    if meeting.approximate:
        lines.append(
            f"≈ Время названо приблизительно, взял {moment:%H:%M}. "
            "Если имелось в виду другое — напишите точнее."
        )
    # Внутри блока нет пустых строк: по ним split_message делит длинный ответ.
    return "\n".join(lines)


def format_reply(extraction: Extraction, zones: Sequence[Zone], now: datetime) -> str:
    blocks = [format_meeting(meeting, zones, now) for meeting in extraction.meetings]
    if extraction.skipped:
        count = extraction.skipped
        blocks.append(
            f"… и ещё {count} {plural(count, 'встреча', 'встречи', 'встреч')}: "
            f"за раз разбираю не больше {MAX_MEETINGS}."
        )
    if extraction.errors:
        blocks.append(
            "⚠️ Не удалось разобрать:\n" + "\n".join(f"• {escape(error)}" for error in extraction.errors)
        )
    return "\n\n".join(blocks)


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Делит ответ на сообщения по границам блоков, чтобы не разрезать HTML-разметку."""
    chunks: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = block
    if current:
        chunks.append(current)
    return chunks
