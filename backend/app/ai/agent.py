"""Агент чата: модель + инструменты + стриминг ответа.

Цикл на MAX_TOOL_ROUNDS раундов:
  1. Спрашиваем модель, дав ей описание инструментов (tools).
  2. Попросила инструмент — выполняем, результат кладём обратно в диалог
     и спрашиваем снова. Так модель может уточнить запрос по итогам первого
     ответа базы: посчитала по статусам -> увидела перекос -> полезла за строками.
  3. Ответила текстом вместо инструмента — это и есть финальный ответ.

Лишних вызовов нет: текст, который модель уже сформулировала, отдаётся как есть,
кусками. Отдельный стриминговый вызов делается только если раунды кончились,
а модель всё ещё просит инструменты — чтобы диалог не завис без ответа.

Наружу генератор отдаёт события-словари, роут превращает их в SSE:
  {"type": "tool",  "round": 1, "name": ..., "arguments": {...}, "result": {...}}
  {"type": "delta", "text": "кусок ответа"}
  {"type": "done",  "meta": {"total_tokens": ..., "cost_usd": ..., "latency_ms": ...}}
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.ai.client import LlmResult, stream_text
from app.ai.client import complete as llm_complete
from app.ai.tools import TOOL_DEFINITIONS, run_tool

MAX_TOOL_ROUNDS = 3           # столько раз подряд модель может попросить инструменты
MAX_TOOL_RESULT_CHARS = 6000  # столько результата инструмента отдаём модели

SYSTEM_PROMPT = """Ты — ассистент внутри рабочей панели. У тебя есть доступ к базе данных
через инструменты. Правила:

1. Прежде чем отвечать на вопрос про данные — обязательно посмотри в базу инструментом,
   не выдумывай цифры и не отвечай по памяти.
2. Для «сколько / на какую сумму / средний / по дням» бери aggregate_metrics,
   для конкретных строк — query_records.
3. create_record вызывай только если пользователь прямо просит что-то создать.
4. Отвечай по-русски, коротко и по делу, цифры называй точно, как вернул инструмент.
5. Если данных не хватает — так и скажи, какого фильтра или уточнения не хватает."""


def build_messages(user_message: str, history: list[dict] | None = None) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in (history or [])[-10:]:  # последние 10 реплик, чтобы не раздувать промпт
        role, content = item.get("role"), item.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages


def _chunk(text: str, size: int = 24) -> Iterator[str]:
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _meta(result: LlmResult, tools_used: list[str]) -> dict:
    return {
        "status": result.status,
        "model": result.model,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.total_tokens,
        "latency_ms": result.latency_ms,
        "cost_usd": result.cost_usd,
        "tools_used": tools_used,
        "error": result.error,
    }


def run_agent_stream(db: Session, user_message: str, history: list[dict] | None = None) -> Iterator[dict]:
    """Главная точка входа чата. Исключений не бросает: при любой проблеме
    с API придёт заглушка со status="fallback"."""
    messages = build_messages(user_message, history)
    tools_used: list[str] = []

    for round_number in range(1, MAX_TOOL_ROUNDS + 1):
        decision = llm_complete(
            db,
            messages,
            purpose="chat.tools",
            tools=TOOL_DEFINITIONS,
            use_cache=False,  # диалог каждый раз новый, кэш тут только мешает
            temperature=0.2,
        )

        if not decision.tool_calls:
            # Модель закончила: её текст — готовый ответ (или заглушка, если API
            # недоступен). Отдельный вызов ради «настоящего» стриминга был бы
            # лишними деньгами, поэтому режем готовый текст на куски.
            for piece in _chunk(decision.text):
                yield {"type": "delta", "text": piece}
            yield {"type": "done", "meta": _meta(decision, tools_used)}
            return

        messages.append(
            {
                "role": "assistant",
                "content": decision.text or None,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call["arguments"]},
                    }
                    for call in decision.tool_calls
                ],
            }
        )

        for call in decision.tool_calls:
            output = run_tool(db, call["name"], call["arguments"])
            tools_used.append(call["name"])
            try:
                arguments = json.loads(call["arguments"])
            except json.JSONDecodeError:
                arguments = {"raw": call["arguments"]}
            yield {
                "type": "tool",
                "round": round_number,
                "name": call["name"],
                "arguments": arguments,
                "result": output,
            }
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(output, ensure_ascii=False, default=str)[:MAX_TOOL_RESULT_CHARS],
                }
            )

    # Раунды кончились, а модель всё ещё просит инструменты. Просим её ответить
    # тем, что уже есть, — без инструментов и стримом, чтобы диалог не завис.
    for kind, payload in stream_text(db, messages, purpose="chat.answer"):
        if kind == "delta":
            yield {"type": "delta", "text": payload}
        else:
            yield {"type": "done", "meta": _meta(payload, tools_used)}
