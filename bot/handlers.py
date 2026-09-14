"""Обработчики Telegram. В группах реагируем только на упоминание бота или /time."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Optional

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, User

from .config import Config
from .mentions import Entity, strip_bot_mentions
from .parsing import UserFacingError
from .service import NOT_FOUND_TEXT, ExtractFn, resolve

log = logging.getLogger(__name__)
router = Router(name="timezones")


@dataclass(frozen=True)
class Candidate:
    text: str
    ref: datetime  # момент написания в зоне автора


def _text(message: Message) -> str:
    return message.text or message.caption or ""


def _entities(message: Message) -> list[Entity]:
    source = message.entities if message.text else message.caption_entities
    return [
        Entity(e.type, e.offset, e.length, e.user.id if e.user else None)
        for e in source or ()
    ]


def _ref(message: Message, config: Config) -> datetime:
    user = message.from_user
    tz = config.zone_for_user(user.id if user else None, user.username if user else None)
    return message.date.astimezone(tz)


def _reply_candidate(message: Message, config: Config, me: User) -> Optional[Candidate]:
    source = message.reply_to_message
    if source is None or (source.from_user and source.from_user.id == me.id):
        return None
    # Если пользователь процитировал фрагмент — разбираем только его.
    text = message.quote.text if message.quote else _text(source)
    if not text.strip():
        return None
    return Candidate(text, _ref(source, config))


async def _answer(message: Message, candidates: list[Candidate], config: Config, extract: ExtractFn, me: User) -> None:
    if not candidates:
        await message.reply(
            "Упомяните меня реплаем на сообщение со временем или прямо в нём:\n"
            f"<i>@{escape(me.username or '')} созвон завтра в 15:00 по мск</i>"
        )
        return
    try:
        # Сначала текст рядом с упоминанием, затем сообщение, на которое ответили.
        for candidate in candidates:
            result = await resolve(candidate.text, candidate.ref, config.zones, extract)
            if result.found:
                await message.reply(result.reply)
                return
    except UserFacingError as error:
        await message.reply(escape(error.message))
        return
    except Exception:
        log.exception("Необработанная ошибка при разборе")
        await message.reply("Что-то пошло не так. Попробуйте ещё раз.")
        return
    await message.reply(NOT_FOUND_TEXT)


@router.message(Command("time", "tz"))
async def on_command(message: Message, command: CommandObject, config: Config, extract: ExtractFn, me: User) -> None:
    candidates = []
    if command.args:
        candidates.append(Candidate(command.args, _ref(message, config)))
    reply = _reply_candidate(message, config, me)
    if reply:
        candidates.append(reply)
    await _answer(message, candidates, config, extract, me)


@router.message(F.text | F.caption)
async def on_message(message: Message, config: Config, extract: ExtractFn, me: User) -> None:
    mentioned, own_text = strip_bot_mentions(_text(message), _entities(message), me.username or "", me.id)
    if not mentioned and message.chat.type != ChatType.PRIVATE:
        # Сюда попадают, например, реплаи на сообщения бота без упоминания. Не читаем и не логируем.
        return

    candidates = []
    if own_text.strip():
        candidates.append(Candidate(own_text, _ref(message, config)))
    reply = _reply_candidate(message, config, me)
    if reply:
        candidates.append(reply)
    await _answer(message, candidates, config, extract, me)
