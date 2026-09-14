"""Поиск и вырезание обращений к боту: @упоминание или /time в любом месте. Смещения сущностей Telegram — в UTF-16."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

TRIGGER_COMMANDS = frozenset({"time", "tz"})


@dataclass(frozen=True)
class Entity:
    type: str
    offset: int
    length: int
    user_id: Optional[int] = None


def strip_bot_triggers(
    text: str,
    entities: Iterable[Entity],
    bot_username: str,
    bot_id: int,
    commands: frozenset = TRIGGER_COMMANDS,
) -> tuple[bool, str]:
    """Возвращает (к боту обратились, текст без обращений к боту)."""
    encoded = text.encode("utf-16-le")
    username = bot_username.casefold()
    spans = []
    for entity in entities:
        start, end = entity.offset * 2, (entity.offset + entity.length) * 2
        value = encoded[start:end].decode("utf-16-le")
        if entity.type == "mention":
            if username and value.lstrip("@").casefold() == username:
                spans.append((start, end))
        elif entity.type == "text_mention":
            if entity.user_id == bot_id:
                spans.append((start, end))
        elif entity.type == "bot_command":
            name, _, target = value.lstrip("/").partition("@")
            if name.casefold() in commands and (not target or target.casefold() == username):
                spans.append((start, end))

    if not spans:
        return False, text
    for start, end in sorted(spans, reverse=True):
        encoded = encoded[:start] + encoded[end:]
    return True, " ".join(encoded.decode("utf-16-le").split())
