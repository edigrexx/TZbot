"""Вызов Claude: только извлечение даты/времени/зоны в JSON."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Iterable

import anthropic

from .config import Zone
from .parsing import UserFacingError
from .prompt import build_system_prompt

log = logging.getLogger(__name__)

API_TIMEOUT_SECONDS = 10.0
MAX_TOKENS = 200

# Structured outputs: API гарантирует валидный JSON по схеме, без markdown-обёртки.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "date": {"type": "string"},
        "time": {"type": "string"},
        "offset_minutes": {"type": "integer"},
        "tz": {"type": "string"},
        "tz_explicit": {"type": "boolean"},
        "approximate": {"type": "boolean"},
    },
    "required": ["found"],
    "additionalProperties": False,
}


class ClaudeExtractor:
    def __init__(self, api_key: str, model: str, zones: Iterable[Zone], timeout: float = API_TIMEOUT_SECONDS):
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=1)
        self._model = model
        self._zones = tuple(zones)
        self._timeout = timeout

    async def __call__(self, text: str, ref: datetime) -> str:
        try:
            # Общий потолок на вызов вместе с ретраем SDK.
            async with asyncio.timeout(self._timeout):
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=MAX_TOKENS,
                    temperature=0,
                    system=build_system_prompt(ref, self._zones),
                    messages=[{"role": "user", "content": f"<message>\n{text}\n</message>"}],
                    output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
                )
        except (TimeoutError, anthropic.APITimeoutError):
            log.warning("Claude: таймаут %.0f с, text=%r", self._timeout, text)
            raise UserFacingError(
                f"⏱ Модель не ответила за {self._timeout:.0f} секунд. Попробуйте ещё раз чуть позже."
            ) from None
        except anthropic.RateLimitError:
            log.warning("Claude: rate limit")
            raise UserFacingError("Слишком много запросов к модели — попробуйте через минуту.") from None
        except anthropic.APIConnectionError as error:
            log.warning("Claude: нет соединения: %s", error)
            raise UserFacingError("Не удалось связаться с моделью. Попробуйте ещё раз.") from None
        except anthropic.APIStatusError as error:
            log.error("Claude: HTTP %s: %s", error.status_code, error.message)
            raise UserFacingError(f"Модель вернула ошибку (HTTP {error.status_code}).") from None

        if response.stop_reason == "refusal":
            log.warning("Claude: refusal, text=%r", text)
            raise UserFacingError("Модель отказалась разбирать это сообщение.")
        return "".join(block.text for block in response.content if block.type == "text")

    async def close(self) -> None:
        await self._client.close()
