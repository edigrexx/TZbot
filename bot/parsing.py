"""Строгая валидация JSON-ответа модели: список встреч."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from .config import get_zone

MAX_MEETINGS = 8
MAX_TITLE_LENGTH = 80
MAX_OFFSET_MINUTES = 60 * 24 * 31

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME = re.compile(r"\d{2}:\d{2}")


class UserFacingError(Exception):
    """Ошибка, текст которой можно показать в чате."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Meeting:
    moment: datetime  # aware, в зоне, где названо время
    title: Optional[str] = None
    approximate: bool = False
    tz_explicit: bool = True


@dataclass(frozen=True)
class Extraction:
    meetings: tuple[Meeting, ...] = ()
    errors: tuple[str, ...] = ()  # встречи, которые не удалось разобрать
    skipped: int = 0  # встречи сверх MAX_MEETINGS

    @property
    def found(self) -> bool:
        return bool(self.meetings)


def parse_model_output(raw: str, ref: datetime) -> Extraction:
    """Бросает UserFacingError, если ответ не разобран целиком или не разобралась ни одна встреча."""
    text = raw.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise UserFacingError(
            "Не удалось разобрать ответ модели. Попробуйте переформулировать."
        ) from None

    items = data.get("meetings") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise UserFacingError("Модель вернула ответ в неожиданном формате.")

    meetings: list[Meeting] = []
    errors: list[str] = []
    for item in items[:MAX_MEETINGS]:
        title = _title(item.get("title")) if isinstance(item, dict) else None
        try:
            if not isinstance(item, dict):
                raise UserFacingError("Модель вернула встречу в неожиданном формате.")
            meetings.append(_meeting(item, ref, title))
        except UserFacingError as error:
            errors.append(f"«{title}»: {error.message}" if title else error.message)

    if not meetings and errors:
        raise UserFacingError("\n".join(errors))
    return Extraction(tuple(meetings), tuple(errors), max(0, len(items) - MAX_MEETINGS))


def _title(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    title = " ".join(value.split())
    if len(title) > MAX_TITLE_LENGTH:
        title = title[: MAX_TITLE_LENGTH - 1].rstrip() + "…"
    return title or None


def _meeting(item: dict, ref: datetime, title: Optional[str]) -> Meeting:
    tz_name = item.get("tz")
    if not isinstance(tz_name, str) or not tz_name:
        raise UserFacingError("Модель не указала часовой пояс.")
    try:
        tz = get_zone(tz_name)
    except ValueError:
        raise UserFacingError(f"Не знаю часовой пояс «{tz_name}».") from None

    offset = item.get("offset_minutes")
    if offset is not None:
        moment = _relative_moment(offset, ref, tz)
    else:
        moment = _local_moment(item.get("date"), item.get("time"), tz)

    return Meeting(
        moment=moment,
        title=title,
        approximate=item.get("approximate") is True,
        tz_explicit=item.get("tz_explicit") is not False,
    )


def _relative_moment(offset: object, ref: datetime, tz: ZoneInfo) -> datetime:
    if isinstance(offset, bool) or not isinstance(offset, int) or abs(offset) > MAX_OFFSET_MINUTES:
        raise UserFacingError(f"Некорректное смещение от модели: {offset!r}.")
    moment = ref.astimezone(timezone.utc) + timedelta(minutes=offset)
    return moment.astimezone(tz).replace(second=0, microsecond=0)


def _local_moment(date_raw: object, time_raw: object, tz: ZoneInfo) -> datetime:
    if not isinstance(date_raw, str) or not _DATE.fullmatch(date_raw):
        raise UserFacingError(f"Некорректная дата от модели: {date_raw!r}.")
    if not isinstance(time_raw, str) or not _TIME.fullmatch(time_raw):
        raise UserFacingError(f"Некорректное время от модели: {time_raw!r}.")
    try:
        naive = datetime.strptime(f"{date_raw} {time_raw}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise UserFacingError(
            f"Такой даты или времени не бывает: {date_raw} {time_raw}."
        ) from None

    aware = naive.replace(tzinfo=tz)
    # Время, попавшее в «дыру» перевода часов, не переживает круг через UTC.
    roundtrip = aware.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)
    if roundtrip != naive:
        raise UserFacingError(
            f"{date_raw} {time_raw} не существует в зоне {tz.key}: в этот момент переводят часы."
        )
    return aware
