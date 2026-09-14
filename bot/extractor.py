"""Вызов LLM через OpenRouter: только извлечение даты/времени/зоны в JSON."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Sequence

import openai

from .config import Zone
from .parsing import UserFacingError
from .prompt import build_system_prompt

log = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
API_TIMEOUT_SECONDS = 10.0
# Потолок, а не расход: одна встреча в JSON ~80 токенов, но у «думающих» моделей рассуждения входят в тот же лимит.
MAX_TOKENS = 2000
MAX_MODELS = 3  # OpenRouter принимает основную модель и до двух запасных

# Все поля обязательны, ненужные — null: так схема проходит strict-режим и у OpenAI, и у Gemini.
MEETING_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": ["string", "null"], "description": "Short meeting name from the text"},
        "date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "time": {"type": ["string", "null"], "description": "HH:MM, 24h"},
        "offset_minutes": {"type": ["integer", "null"]},
        "tz": {"type": ["string", "null"], "description": "IANA time zone"},
        "tz_explicit": {"type": ["boolean", "null"]},
        "approximate": {"type": ["boolean", "null"]},
    },
    "required": ["title", "date", "time", "offset_minutes", "tz", "tz_explicit", "approximate"],
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"meetings": {"type": "array", "items": MEETING_SCHEMA}},
    "required": ["meetings"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class CallStats:
    model: str
    latency: float
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    cost: Optional[float]


class OpenRouterExtractor:
    def __init__(
        self,
        api_key: str,
        model: str,
        fallback_models: Sequence[str],
        reasoning_effort: Optional[str],
        zones: Iterable[Zone],
        timeout: float = API_TIMEOUT_SECONDS,
    ):
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            timeout=timeout,
            max_retries=1,
            default_headers={"HTTP-Referer": "https://github.com/edigrexx/TZbot", "X-Title": "TZbot"},
        )
        self._model = model
        self._models = [model, *fallback_models][:MAX_MODELS]
        if len(fallback_models) + 1 > MAX_MODELS:
            log.warning("OpenRouter принимает не больше %d моделей, лишние запасные отброшены", MAX_MODELS)
        self._reasoning_effort = reasoning_effort
        self._zones = tuple(zones)
        self._timeout = timeout
        self.last_stats: Optional[CallStats] = None

    async def __call__(self, text: str, ref: datetime) -> str:
        extra_body: dict = {"usage": {"include": True}}
        if len(self._models) > 1:
            extra_body["models"] = self._models
        if self._reasoning_effort:
            extra_body["reasoning"] = {"effort": self._reasoning_effort, "exclude": True}

        started = time.monotonic()
        try:
            # Общий потолок на вызов вместе с ретраем SDK.
            async with asyncio.timeout(self._timeout):
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": build_system_prompt(ref, self._zones)},
                        {"role": "user", "content": f"<message>\n{text}\n</message>"},
                    ],
                    max_tokens=MAX_TOKENS,
                    temperature=0,  # OpenRouter молча отбрасывает параметр, если модель его не поддерживает
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": "meetings", "strict": True, "schema": OUTPUT_SCHEMA},
                    },
                    extra_body=extra_body,
                )
        except (TimeoutError, openai.APITimeoutError):
            log.warning("LLM: таймаут %.0f с, text=%r", self._timeout, text)
            raise UserFacingError(
                f"⏱ Модель не ответила за {self._timeout:.0f} секунд. Попробуйте ещё раз чуть позже."
            ) from None
        except openai.RateLimitError:
            log.warning("LLM: rate limit")
            raise UserFacingError("Слишком много запросов к модели — попробуйте через минуту.") from None
        except openai.APIConnectionError as error:
            log.warning("LLM: нет соединения: %s", error)
            raise UserFacingError("Не удалось связаться с моделью. Попробуйте ещё раз.") from None
        except openai.APIStatusError as error:
            log.error("LLM: HTTP %s: %s", error.status_code, error.message)
            if error.status_code == 402:
                raise UserFacingError("На балансе OpenRouter закончились кредиты.") from None
            raise UserFacingError(f"Модель вернула ошибку (HTTP {error.status_code}).") from None

        usage = response.usage
        choice = response.choices[0] if response.choices else None
        self.last_stats = CallStats(
            model=response.model,
            latency=time.monotonic() - started,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            cost=getattr(usage, "cost", None),
        )
        log.info(
            "LLM model=%s finish=%s tokens=%s/%s cost=%s latency=%.2fs",
            self.last_stats.model, choice.finish_reason if choice else None,
            self.last_stats.prompt_tokens, self.last_stats.completion_tokens,
            self.last_stats.cost, self.last_stats.latency,
        )

        content = choice.message.content if choice else None
        if not content:
            log.warning("LLM: пустой ответ: %s", response.model_dump_json()[:500])
            raise UserFacingError("Модель вернула пустой ответ. Попробуйте ещё раз.")
        if choice.finish_reason == "length":
            raise UserFacingError("Модель не уложилась в лимит ответа. Попробуйте ещё раз.")
        return content

    async def close(self) -> None:
        await self._client.close()
