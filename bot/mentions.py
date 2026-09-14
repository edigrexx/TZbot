"""Поиск и вырезание упоминаний бота. Смещения сущностей Telegram — в UTF-16."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class Entity:
    type: str
    offset: int
    length: int
    user_id: Optional[int] = None


def strip_bot_mentions(
    text: str, entities: Iterable[Entity], bot_username: str, bot_id: int
) -> tuple[bool, str]:
    """Возвращает (бот упомянут, текст без упоминаний бота)."""
    encoded = text.encode("utf-16-le")
    spans = []
    for entity in entities:
        start, end = entity.offset * 2, (entity.offset + entity.length) * 2
        if entity.type == "mention":
            value = encoded[start:end].decode("utf-16-le")
            if bot_username and value.lstrip("@").casefold() == bot_username.casefold():
                spans.append((start, end))
        elif entity.type == "text_mention" and entity.user_id == bot_id:
            spans.append((start, end))

    if not spans:
        return False, text
    for start, end in sorted(spans, reverse=True):
        encoded = encoded[:start] + encoded[end:]
    return True, " ".join(encoded.decode("utf-16-le").split())
