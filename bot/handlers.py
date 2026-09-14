"""Обработчики Telegram.

Обратиться к боту можно @упоминанием или командой /time в любом месте сообщения — в том числе реплаем
на сообщение со временем. В группах это требует выключенного privacy mode: иначе Telegram не доставляет
боту ни упоминания, ни команды в середине текста. Сообщения без обращения к боту отбрасываются
сразу — не логируются и не уходят в модель.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Optional

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message, User

from .config import Config
from .convert import split_message
from .mentions import Entity, strip_bot_triggers
from .parsing import UserFacingError
from .service import NOT_FOUND_TEXT, ExtractFn, resolve

log = logging.getLogger(__name__)
router = Router(name="timezones")

TIME_COMMAND_DESCRIPTION = "Пересчитать время встречи во все зоны команды"


@dataclass(frozen=True)
class Candidate:
    text: str
    ref: datetime  # момент написания в зоне автора


def help_text(me: User) -> str:
    bot = escape(me.username or "")
    return (
        "Пересчитываю время встречи во все часовые пояса команды.\n\n"
        "<b>Как позвать</b>\n"
        f"• отметьте меня в сообщении со временем: <i>Встреча в четверг в 17:00 по алматы @{bot}</i>\n"
        f"• ответьте на сообщение со временем и отметьте меня: <i>@{bot}</i>\n"
        "• вместо отметки можно написать <code>/time</code> в любом месте сообщения\n\n"
        "<b>В личке</b> — просто напишите сообщение со временем."
    )


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
    if source is not None and source.from_user and source.from_user.id == me.id:
        return None
    # Цитата — часть самого сообщения, поэтому доступна даже без reply_to_message.
    if message.quote and message.quote.text.strip():
        return Candidate(message.quote.text, _ref(source or message, config))
    if source is None:
        return None
    text = _text(source)
    # В темах форума reply_to_message указывает на служебное сообщение о создании темы — у него нет текста.
    if not text.strip():
        return None
    return Candidate(text, _ref(source, config))


def _log_trigger(message: Message, own_text: str) -> None:
    # Только структура, без текстов: помогает понять, что Telegram передал боту.
    source = message.reply_to_message
    log.info(
        "обращение chat=%s type=%s own_text=%s reply=%s reply_type=%s reply_text=%s quote=%s external_reply=%s",
        message.chat.id, message.chat.type, bool(own_text.strip()),
        source is not None, source.content_type if source else None,
        bool(source and _text(source).strip()), message.quote is not None, message.external_reply is not None,
    )


async def _answer(message: Message, candidates: list[Candidate], config: Config, extract: ExtractFn) -> None:
    try:
        # Сначала собственный текст, затем сообщение, на которое ответили.
        for candidate in candidates:
            result = await resolve(candidate.text, candidate.ref, config.zones, extract)
            if result.found:
                for chunk in split_message(result.reply):
                    await message.reply(chunk)
                return
    except UserFacingError as error:
        await message.reply(escape(error.message))
        return
    except Exception:
        log.exception("Необработанная ошибка при разборе")
        await message.reply("Что-то пошло не так. Попробуйте ещё раз.")
        return
    await message.reply(NOT_FOUND_TEXT)


@router.message(Command("start", "help"))
async def on_help(message: Message, me: User) -> None:
    await message.reply(help_text(me))


@router.message(F.text | F.caption)
async def on_message(message: Message, config: Config, extract: ExtractFn, me: User) -> None:
    triggered, own_text = strip_bot_triggers(_text(message), _entities(message), me.username or "", me.id)
    if not triggered and message.chat.type != ChatType.PRIVATE:
        # Обычная переписка чата: не читаем, не логируем, в модель не отправляем.
        return

    _log_trigger(message, own_text)
    candidates = []
    if own_text.strip():
        candidates.append(Candidate(own_text, _ref(message, config)))
    reply = _reply_candidate(message, config, me)
    if reply:
        candidates.append(reply)

    if candidates:
        await _answer(message, candidates, config, extract)
    elif message.reply_to_message is not None or message.external_reply is not None:
        await message.reply(
            "Не вижу текста сообщения, на которое вы ответили — Telegram его не передал.\n"
            "Проверьте, что у бота выключен privacy mode, или напишите время прямо в сообщении."
        )
    else:
        await message.reply(help_text(me))
