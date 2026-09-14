"""Разбор одного текста: модель → валидация → пересчёт. Без зависимостей от Telegram и SDK."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Optional, Sequence

from .config import Zone
from .convert import format_reply
from .parsing import UserFacingError, parse_model_output

log = logging.getLogger(__name__)

ExtractFn = Callable[[str, datetime], Awaitable[str]]

NOT_FOUND_TEXT = "🤷 Не нашёл в сообщении времени встречи."


@dataclass(frozen=True)
class Result:
    found: bool
    reply: Optional[str] = None  # HTML


async def resolve(text: str, ref: datetime, zones: Sequence[Zone], extract: ExtractFn) -> Result:
    """Бросает UserFacingError, если модель недоступна или ответила некорректно."""
    raw = await extract(text, ref)
    try:
        extraction = parse_model_output(raw, ref)
    except UserFacingError as error:
        log.warning("разбор text=%r ref=%s model=%r ошибка=%s", text, ref.isoformat(), raw, error.message)
        raise

    if not extraction.found:
        log.info("разбор text=%r ref=%s model=%r результат=не найдено", text, ref.isoformat(), raw)
        return Result(found=False)

    assert extraction.moment is not None
    log.info(
        "разбор text=%r ref=%s model=%r результат=%s approximate=%s",
        text, ref.isoformat(), raw, extraction.moment.isoformat(), extraction.approximate,
    )
    return Result(found=True, reply=format_reply(extraction, zones, ref))
