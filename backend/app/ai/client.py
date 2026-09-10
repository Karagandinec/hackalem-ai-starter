"""Обёртка над OpenAI API: ретраи, таймауты, лимит токенов, кэш, лог, фолбэк.

Всё, что связано с моделью, живёт здесь. Роуты вызывают только `complete()`
и `stream_text()` и не знают ни про SDK, ни про ретраи.

Главное свойство: **эти функции не падают**. Нет ключа, кончились деньги, лёг
интернет — вернётся заглушка со статусом "fallback", и демо на сцене продолжит
работать. Статус виден в ответе и на странице /ai-metrics.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AiCache, AiCall, utcnow

# --- Цены, USD за 1 000 000 токенов. Модели меняются — правь тут. ------------
PRICING: dict[str, tuple[float, float]] = {
    # model: (input, output)
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    price_in, price_out = PRICING.get(model, (0.0, 0.0))
    return round(prompt_tokens / 1e6 * price_in + completion_tokens / 1e6 * price_out, 6)


@dataclass
class LlmResult:
    """Результат обращения к модели. status: ok | cached | fallback | error."""

    text: str = ""
    data: dict | None = None  # разобранный JSON при structured output
    tool_calls: list[dict] = field(default_factory=list)
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    cached: bool = False
    status: str = "ok"
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "cached")


# --- Кэш --------------------------------------------------------------------


def _cache_key(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(db: Session, key: str) -> dict | None:
    if not settings.ai_cache_enabled:
        return None
    row = db.get(AiCache, key)
    if row is None:
        return None
    if utcnow() - row.created_at > timedelta(seconds=settings.ai_cache_ttl_seconds):
        db.delete(row)
        db.commit()
        return None
    return json.loads(row.response_json)


def _cache_put(db: Session, key: str, value: dict) -> None:
    if not settings.ai_cache_enabled:
        return
    db.merge(AiCache(key=key, response_json=json.dumps(value, ensure_ascii=False), created_at=utcnow()))
    db.commit()


# --- Лог вызовов ------------------------------------------------------------


def log_call(db: Session, purpose: str, prompt: str, result: LlmResult) -> AiCall:
    """Пишет вызов в ai_calls. Сводка по таблице — GET /api/ai/metrics."""
    response_text = result.text
    if not response_text and result.data is not None:
        response_text = json.dumps(result.data, ensure_ascii=False)
    row = AiCall(
        purpose=purpose,
        model=result.model or settings.openai_model,
        prompt=prompt[:8000],
        response=response_text[:8000],
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
        cached=result.cached,
        status=result.status,
        error=result.error,
        tool_calls=json.dumps(result.tool_calls, ensure_ascii=False) if result.tool_calls else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- Заглушка-фолбэк --------------------------------------------------------

FALLBACK_TEXT = (
    "Демо-режим: OpenAI API сейчас недоступен (нет ключа или ошибка сети), "
    "поэтому это заглушка. Логика приложения работает, данные из базы настоящие. "
    "Поставь OPENAI_API_KEY в .env и перезапусти backend."
)


def stub_from_schema(schema: dict) -> Any:
    """Собирает пустышку нужной формы по JSON Schema — чтобы фронт не сломался,
    когда модель недоступна."""
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {name: stub_from_schema(sub) for name, sub in schema.get("properties", {}).items()}
    if kind == "array":
        return [stub_from_schema(schema.get("items", {"type": "string"}))]
    if kind in ("number", "integer"):
        return 0
    if kind == "boolean":
        return False
    return "—"


def _fallback(schema: dict | None, error: str | None, started: float) -> LlmResult:
    return LlmResult(
        text=FALLBACK_TEXT,
        data=stub_from_schema(schema) if schema else None,
        model=settings.openai_model,
        latency_ms=int((time.perf_counter() - started) * 1000),
        status="fallback",
        error=error,
    )


# --- Клиент -----------------------------------------------------------------


def _client():
    from openai import OpenAI

    # max_retries=0: ретраим сами, чтобы контролировать паузы и не ждать вечно.
    return OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds, max_retries=0)


def _is_retryable(exc: Exception) -> bool:
    """Ретраим сеть, таймауты, 429 и 5xx. Битый ключ или кривой запрос — нет."""
    if type(exc).__name__ in ("APITimeoutError", "APIConnectionError", "RateLimitError", "InternalServerError"):
        return True
    code = getattr(exc, "status_code", None)
    return code is not None and (code == 429 or code >= 500)


def complete(
    db: Session,
    messages: list[dict],
    *,
    purpose: str = "generic",
    json_schema: dict | None = None,
    schema_name: str = "result",
    tools: list[dict] | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    use_cache: bool = True,
    log: bool = True,
) -> LlmResult:
    """Один вызов модели.

    json_schema — Structured Outputs: модель обязана вернуть JSON ровно такой
    формы, он придёт в result.data.
    tools — function calling: модель может попросить вызвать инструмент, просьбы
    придут в result.tool_calls (выполняет их agent.py).
    """
    started = time.perf_counter()
    max_tokens = max_tokens or settings.openai_max_output_tokens
    prompt_repr = json.dumps(messages, ensure_ascii=False)

    if not settings.ai_enabled:
        result = _fallback(json_schema, "OPENAI_API_KEY не задан", started)
        if log:
            log_call(db, purpose, prompt_repr, result)
        return result

    key = _cache_key(
        {
            "model": settings.openai_model,
            "messages": messages,
            "schema": json_schema,
            "tools": [t["function"]["name"] for t in tools] if tools else None,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
    )
    if use_cache:
        hit = _cache_get(db, key)
        if hit is not None:
            result = LlmResult(**hit)
            result.cached = True
            result.status = "cached"
            result.cost_usd = 0.0
            result.latency_ms = int((time.perf_counter() - started) * 1000)
            if log:
                log_call(db, purpose, prompt_repr, result)
            return result

    kwargs: dict = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": temperature,
        # max_completion_tokens, а не max_tokens: старый параметр новые модели не принимают.
        "max_completion_tokens": max_tokens,
    }
    if json_schema is not None:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": json_schema, "strict": True},
        }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    response = None
    for attempt in range(max(1, settings.openai_max_retries)):
        try:
            response = _client().chat.completions.create(**kwargs)
            break
        except Exception as exc:  # noqa: BLE001 — наверх ничего не пускаем, демо не должно падать
            last = attempt == max(1, settings.openai_max_retries) - 1
            if not _is_retryable(exc) or last:
                result = _fallback(json_schema, f"{type(exc).__name__}: {exc}", started)
                if log:
                    log_call(db, purpose, prompt_repr, result)
                return result
            time.sleep(0.5 * 2**attempt)  # 0.5s, 1s, 2s...

    message = response.choices[0].message
    usage = response.usage
    result = LlmResult(
        text=message.content or "",
        model=response.model,
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        total_tokens=usage.total_tokens if usage else 0,
        latency_ms=int((time.perf_counter() - started) * 1000),
        status="ok",
    )
    result.cost_usd = estimate_cost(result.model, result.prompt_tokens, result.completion_tokens)

    if message.tool_calls:
        result.tool_calls = [
            {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
            for tc in message.tool_calls
        ]
    if json_schema is not None and result.text:
        try:
            result.data = json.loads(result.text)
        except json.JSONDecodeError as exc:
            result.status = "error"
            result.error = f"Модель вернула не-JSON: {exc}"

    if use_cache and result.status == "ok" and not result.tool_calls:
        _cache_put(db, key, result.__dict__)
    if log:
        log_call(db, purpose, prompt_repr, result)
    return result


def stream_text(
    db: Session,
    messages: list[dict],
    *,
    purpose: str = "chat",
    temperature: float = 0.3,
    max_tokens: int | None = None,
) -> Iterator[tuple[str, str | LlmResult]]:
    """Стриминг ответа: отдаёт ("delta", кусок текста) ... и в конце ("done", LlmResult).

    Кэш при стриминге намеренно не используется: живая печать — часть демо.
    """
    started = time.perf_counter()
    max_tokens = max_tokens or settings.openai_max_output_tokens
    prompt_repr = json.dumps(messages, ensure_ascii=False)

    if not settings.ai_enabled:
        yield from _stream_fallback()
        result = _fallback(None, "OPENAI_API_KEY не задан", started)
        log_call(db, purpose, prompt_repr, result)
        yield ("done", result)
        return

    chunks: list[str] = []
    usage = None
    model = settings.openai_model
    try:
        stream = _client().chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=temperature,
            max_completion_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            if chunk.usage:
                usage = chunk.usage
            model = chunk.model or model
            if chunk.choices and chunk.choices[0].delta.content:
                piece = chunk.choices[0].delta.content
                chunks.append(piece)
                yield ("delta", piece)
    except Exception as exc:  # noqa: BLE001
        if not chunks:  # ничего не успели отдать — показываем заглушку
            yield from _stream_fallback()
        result = _fallback(None, f"{type(exc).__name__}: {exc}", started)
        if chunks:
            result.text = "".join(chunks)
        log_call(db, purpose, prompt_repr, result)
        yield ("done", result)
        return

    result = LlmResult(
        text="".join(chunks),
        model=model,
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        total_tokens=usage.total_tokens if usage else 0,
        latency_ms=int((time.perf_counter() - started) * 1000),
        status="ok",
    )
    result.cost_usd = estimate_cost(result.model, result.prompt_tokens, result.completion_tokens)
    log_call(db, purpose, prompt_repr, result)
    yield ("done", result)


def _stream_fallback() -> Iterator[tuple[str, str]]:
    """Печатаем заглушку по словам, чтобы визуально это выглядело как стриминг."""
    for word in FALLBACK_TEXT.split(" "):
        time.sleep(0.02)
        yield ("delta", word + " ")
