from __future__ import annotations

import asyncio
import logging
import os
import sys
from urllib.parse import urlsplit

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeDefault

from .config import Config, ConfigError, load_config
from .extractor import OpenRouterExtractor
from .handlers import TIME_COMMAND_DESCRIPTION, router

log = logging.getLogger("bot")


async def run(config: Config) -> None:
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    extractor = OpenRouterExtractor(
        api_key=config.openrouter_api_key,
        model=config.model,
        fallback_models=config.fallback_models,
        reasoning_effort=config.reasoning_effort,
        zones=config.zones,
    )
    try:
        # Long polling не работает, пока у токена установлен webhook (например, от прошлого деплоя).
        webhook = await bot.get_webhook_info()
        if webhook.url:
            log.warning(
                "У бота установлен webhook на %s — удаляю, бот работает через long polling. "
                "Накопленные для webhook обновления (%s) сбрасываются.",
                urlsplit(webhook.url).netloc, webhook.pending_update_count,
            )
            await bot.delete_webhook(drop_pending_updates=True)

        # Меню «/» в личке и группах; без него команду приходится помнить наизусть.
        commands = [
            BotCommand(command="time", description=TIME_COMMAND_DESCRIPTION),
            BotCommand(command="help", description="Как пользоваться"),
        ]
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        await bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())

        me = await bot.get_me()
        log.info(
            "Запущен @%s, модель %s (запасные: %s), зоны: %s, по умолчанию %s",
            me.username, config.model, ", ".join(config.fallback_models) or "нет",
            ", ".join(f"{z.label}={z.tz.key}" for z in config.zones), config.default_tz.key,
        )
        dispatcher = Dispatcher(config=config, extract=extractor, me=me)
        dispatcher.include_router(router)
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await extractor.close()
        await bot.session.close()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    try:
        config = load_config()
    except ConfigError as error:
        log.critical("Ошибка конфигурации: %s", error)
        sys.exit(2)
    asyncio.run(run(config))


if __name__ == "__main__":
    main()
