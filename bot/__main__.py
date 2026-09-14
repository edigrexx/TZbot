from __future__ import annotations

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import Config, ConfigError, load_config
from .extractor import ClaudeExtractor
from .handlers import router

log = logging.getLogger("bot")


async def run(config: Config) -> None:
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    extractor = ClaudeExtractor(config.anthropic_api_key, config.model, config.zones)
    try:
        me = await bot.get_me()
        log.info(
            "Запущен @%s, модель %s, зоны: %s, по умолчанию %s",
            me.username, config.model,
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
