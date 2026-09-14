"""Загрузка и валидация конфигурации из переменных окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Mapping, Optional
from zoneinfo import ZoneInfo, available_timezones

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class ConfigError(Exception):
    pass


@lru_cache(maxsize=1)
def known_timezones() -> frozenset:
    # available_timezones() сканирует диск — считаем один раз.
    return frozenset(available_timezones())


def get_zone(name: str) -> ZoneInfo:
    """ZoneInfo только для имён из available_timezones(), иначе ValueError."""
    if name not in known_timezones():
        raise ValueError(f"unknown timezone: {name}")
    return ZoneInfo(name)


@dataclass(frozen=True)
class Zone:
    label: str
    tz: ZoneInfo


@dataclass(frozen=True)
class Config:
    bot_token: str
    anthropic_api_key: str
    zones: tuple[Zone, ...]
    default_tz: ZoneInfo
    user_timezones: Mapping[str, ZoneInfo] = field(default_factory=dict)
    model: str = DEFAULT_MODEL

    def zone_for_user(self, user_id: Optional[int], username: Optional[str]) -> ZoneInfo:
        if user_id is not None and str(user_id) in self.user_timezones:
            return self.user_timezones[str(user_id)]
        if username and username.casefold() in self.user_timezones:
            return self.user_timezones[username.casefold()]
        return self.default_tz


def _split_pair(item: str, var: str) -> tuple[str, str]:
    if item.count(":") != 1:
        raise ConfigError(
            f"{var}: «{item}» — ожидается ровно одно двоеточие, формат Метка:Zone/Name"
        )
    left, right = (part.strip() for part in item.split(":"))
    return left, right


def _items(raw: str, var: str) -> list[str]:
    items = [item.strip() for item in raw.split(",")]
    for index, item in enumerate(items, start=1):
        if not item:
            raise ConfigError(f"{var}: пустой элемент №{index} (лишняя запятая?)")
    return items


def _zone_or_error(name: str, var: str, owner: str) -> ZoneInfo:
    if not name:
        raise ConfigError(f"{var}: для «{owner}» не указана зона")
    try:
        return get_zone(name)
    except ValueError:
        raise ConfigError(
            f"{var}: зона «{name}» ({owner}) не найдена в базе IANA"
        ) from None


def parse_timezones(raw: str) -> tuple[Zone, ...]:
    """Разбирает TIMEZONES вида `Almaty:Asia/Almaty,MSK:Europe/Moscow`."""
    if not raw or not raw.strip():
        raise ConfigError(
            "TIMEZONES пуста. Формат: Метка:Zone/Name,Метка2:Zone/Name2"
        )
    zones: list[Zone] = []
    seen: set[str] = set()
    for item in _items(raw, "TIMEZONES"):
        label, name = _split_pair(item, "TIMEZONES")
        if not label:
            raise ConfigError(f"TIMEZONES: пустая метка в «{item}»")
        tz = _zone_or_error(name, "TIMEZONES", label)
        if label.casefold() in seen:
            raise ConfigError(f"TIMEZONES: метка «{label}» повторяется")
        seen.add(label.casefold())
        zones.append(Zone(label=label, tz=tz))
    return tuple(zones)


def parse_user_timezones(raw: str) -> dict[str, ZoneInfo]:
    """Разбирает USER_TIMEZONES вида `@username:Asia/Ho_Chi_Minh,123456789:Europe/Moscow`.

    Ключ — числовой Telegram ID или username (без @, без учёта регистра).
    """
    if not raw or not raw.strip():
        return {}
    result: dict[str, ZoneInfo] = {}
    for item in _items(raw, "USER_TIMEZONES"):
        who, name = _split_pair(item, "USER_TIMEZONES")
        key = who.lstrip("@").casefold()
        if not key:
            raise ConfigError(f"USER_TIMEZONES: не указан пользователь в «{item}»")
        result[key] = _zone_or_error(name, "USER_TIMEZONES", who)
    return result


def load_config(env: Optional[Mapping[str, str]] = None) -> Config:
    env = os.environ if env is None else env

    def required(name: str) -> str:
        value = env.get(name, "").strip()
        if not value:
            raise ConfigError(f"Не задана переменная окружения {name}")
        return value

    bot_token = required("BOT_TOKEN")
    api_key = required("ANTHROPIC_API_KEY")
    zones = parse_timezones(required("TIMEZONES"))
    default_tz = _zone_or_error(required("DEFAULT_TZ"), "DEFAULT_TZ", "DEFAULT_TZ")
    return Config(
        bot_token=bot_token,
        anthropic_api_key=api_key,
        zones=zones,
        default_tz=default_tz,
        user_timezones=parse_user_timezones(env.get("USER_TIMEZONES", "")),
        model=env.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL,
    )
