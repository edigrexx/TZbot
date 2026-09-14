"""Строгая валидация JSON-ответа модели."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from .config import get_zone

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
class Extraction:
    found: bool
    moment: Optional[datetime] = None  # aware, в зоне, где названо время
    approximate: bool = False
    tz_explicit: bool = True


def parse_model_output(raw: str, ref: datetime) -> Extraction:
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

    if not isinstance(data, dict) or not isinstance(data.get("found"), bool):
        raise UserFacingError("Модель вернула ответ в неожиданном формате.")
    if not data["found"]:
        return Extraction(found=False)

    tz_name = data.get("tz")
    if not isinstance(tz_name, str) or not tz_name:
        raise UserFacingError("Модель не указала часовой пояс.")
    try:
        tz = get_zone(tz_name)
    except ValueError:
        raise UserFacingError(f"Не знаю часовой пояс «{tz_name}».") from None

    offset = data.get("offset_minutes")
    if offset is not None:
        moment = _relative_moment(offset, ref, tz)
    else:
        moment = _local_moment(data.get("date"), data.get("time"), tz)

    return Extraction(
        found=True,
        moment=moment,
        approximate=data.get("approximate") is True,
        tz_explicit=data.get("tz_explicit") is not False,
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
