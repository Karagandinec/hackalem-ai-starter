"""Тест цикла агента: модель просит инструмент -> инструмент выполняется -> ответ стримом.

Настоящий OpenAI тут не нужен и не нужен ключ: подменяем вызов модели заглушкой.
Это единственное место, где логика агента проверяется целиком, поэтому не удаляй.
"""

import json

from app.ai import agent
from app.ai.client import LlmResult
from app.db import SessionLocal
from app.models import Entity


def test_agent_runs_tool_then_streams(monkeypatch):
    db = SessionLocal()
    try:
        db.add(Entity(name="Для агента", type="заявка", status="new", amount=100.0))
        db.commit()

        def fake_complete(_db, _messages, **_kwargs):
            """Как будто модель попросила посчитать записи."""
            return LlmResult(
                text="",
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "aggregate_metrics",
                        "arguments": json.dumps({"table": "entities", "metric": "count", "group_by": "none"}),
                    }
                ],
                model="fake",
                status="ok",
            )

        def fake_stream(_db, messages, **_kwargs):
            # Результат инструмента обязан попасть в диалог перед финальным вызовом.
            assert any(m.get("role") == "tool" for m in messages)
            yield ("delta", "Записей: ")
            yield ("delta", "много")
            yield ("done", LlmResult(text="Записей: много", model="fake", total_tokens=42, status="ok"))

        monkeypatch.setattr(agent, "llm_complete", fake_complete)
        monkeypatch.setattr(agent, "stream_text", fake_stream)

        events = list(agent.run_agent_stream(db, "Сколько записей?"))
    finally:
        db.close()

    tool_events = [e for e in events if e["type"] == "tool"]
    assert len(tool_events) == 1
    assert tool_events[0]["name"] == "aggregate_metrics"
    assert tool_events[0]["result"]["value"] >= 1  # инструмент реально сходил в базу

    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Записей: много"

    done = events[-1]
    assert done["type"] == "done"
    assert done["meta"]["total_tokens"] == 42
    assert done["meta"]["tools_used"] == ["aggregate_metrics"]


def test_agent_answers_without_tools(monkeypatch):
    """Если инструменты не нужны, второго вызова модели быть не должно."""
    calls = {"stream": 0}

    monkeypatch.setattr(
        agent,
        "llm_complete",
        lambda _db, _messages, **_kw: LlmResult(text="Привет!", model="fake", status="ok"),
    )

    def fake_stream(*_args, **_kwargs):
        calls["stream"] += 1
        yield ("done", LlmResult())

    monkeypatch.setattr(agent, "stream_text", fake_stream)

    db = SessionLocal()
    try:
        events = list(agent.run_agent_stream(db, "привет"))
    finally:
        db.close()

    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Привет!"
    assert calls["stream"] == 0
