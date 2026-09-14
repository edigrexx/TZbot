"""Пересчёт между зонами (только zoneinfo) и форматирование ответа."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Sequence

from .config import Zone
from .parsing import Extraction
from .ru import WEEKDAYS_SHORT, format_date, format_day_shift, format_utc_offset


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


def format_reply(extraction: Extraction, zones: Sequence[Zone], ref: datetime) -> str:
    moment = extraction.moment
    assert moment is not None
    label = source_label(zones, moment.tzinfo.key)  # type: ignore[union-attr]
    date_text = format_date(moment.date(), with_year=moment.year != ref.year)

    rows = convert(moment, zones)
    width = max(len(row.label) for row in rows)
    table = []
    for row in rows:
        line = f"{row.label.ljust(width)}  {row.local:%H:%M}  {format_utc_offset(row.local.utcoffset()):<8}"
        if row.day_shift:
            weekday = WEEKDAYS_SHORT[row.local.weekday()]
            line += f"  {format_day_shift(row.day_shift)}, {weekday} {row.local:%d.%m}"
        table.append(line.rstrip())

    lines = [
        f"📅 <b>{escape(date_text)}, {moment:%H:%M}</b> ({escape(label)})",
        "",
        "<pre>" + escape("\n".join(table)) + "</pre>",
    ]
    if not extraction.tz_explicit:
        lines.append(f"ℹ️ Пояс в сообщении не назван — считаю по {escape(label)}.")
    if extraction.approximate:
        lines.append(
            f"≈ Время названо приблизительно, взял {moment:%H:%M}. "
            "Если имелось в виду другое — напишите точнее."
        )
    return "\n".join(lines)
