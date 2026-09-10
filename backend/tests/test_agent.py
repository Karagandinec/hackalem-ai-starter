"""Тесты цикла агента: модель просит инструменты -> они выполняются -> ответ.

Настоящий OpenAI тут не нужен и ключ не нужен: подменяем вызов модели заглушкой.
Это единственное место, где логика агента проверяется целиком, поэтому не удаляй.
"""

import json

from app.ai import agent
from app.ai.client import LlmResult
from app.db import SessionLocal
from app.models import Entity


def _tool_call(name: str, arguments: dict, call_id: str = "call_1") -> LlmResult:
    return LlmResult(
        text="",
        tool_calls=[{"id": call_id, "name": name, "arguments": json.dumps(arguments)}],
        model="fake",
        status="ok",
    )


def test_agent_runs_tool_then_answers(monkeypatch):
    """Раунд 1 — инструмент, раунд 2 — готовый ответ. Лишних вызовов быть не должно."""
    db = SessionLocal()
    try:
        db.add(Entity(name="Для агента", type="заявка", status="new", amount=100.0))
        db.commit()

        calls = {"complete": 0, "stream": 0}

        def fake_complete(_db, messages, **_kwargs):
            calls["complete"] += 1
            if calls["complete"] == 1:
                return _tool_call("aggregate_metrics", {"table": "entities", "metric": "count", "group_by": "none"})
            # Результат инструмента обязан быть в диалоге до финального ответа.
            assert any(m.get("role") == "tool" for m in messages)
            return LlmResult(text="Записей: много", model="fake", total_tokens=42, status="ok")

        def fake_stream(*_args, **_kwargs):
            calls["stream"] += 1
            yield ("done", LlmResult())

        monkeypatch.setattr(agent, "llm_complete", fake_complete)
        monkeypatch.setattr(agent, "stream_text", fake_stream)

        events = list(agent.run_agent_stream(db, "Сколько записей?"))
    finally:
        db.close()

    tool_events = [e for e in events if e["type"] == "tool"]
    assert len(tool_events) == 1
    assert tool_events[0]["name"] == "aggregate_metrics"
    assert tool_events[0]["round"] == 1
    assert tool_events[0]["result"]["value"] >= 1  # инструмент реально сходил в базу

    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Записей: много"
    assert events[-1]["meta"]["tools_used"] == ["aggregate_metrics"]
    assert calls["stream"] == 0  # финальный ответ уже был, стримить нечего


def test_agent_chains_several_rounds(monkeypatch):
    """Модель может уточнить запрос по итогам первого ответа базы."""
    db = SessionLocal()
    try:
        sequence = [
            _tool_call("aggregate_metrics", {"table": "entities", "metric": "count", "group_by": "status"}, "c1"),
            _tool_call("query_records", {"table": "entities", "limit": 2}, "c2"),
            LlmResult(text="Готово", model="fake", status="ok"),
        ]
        monkeypatch.setattr(agent, "llm_complete", lambda *_a, **_kw: sequence.pop(0))
        events = list(agent.run_agent_stream(db, "Разберись с воронкой"))
    finally:
        db.close()

    rounds = [e["round"] for e in events if e["type"] == "tool"]
    assert rounds == [1, 2]
    assert events[-1]["meta"]["tools_used"] == ["aggregate_metrics", "query_records"]


def test_agent_stops_after_round_limit(monkeypatch):
    """Если модель зациклилась на инструментах — обрываем и просим ответ стримом."""
    db = SessionLocal()
    try:
        monkeypatch.setattr(
            agent,
            "llm_complete",
            lambda *_a, **_kw: _tool_call("query_records", {"table": "entities", "limit": 1}),
        )

        def fake_stream(*_args, **_kwargs):
            yield ("delta", "Хватит")
            yield ("done", LlmResult(text="Хватит", model="fake", status="ok"))

        monkeypatch.setattr(agent, "stream_text", fake_stream)
        events = list(agent.run_agent_stream(db, "зациклись"))
    finally:
        db.close()

    assert len([e for e in events if e["type"] == "tool"]) == agent.MAX_TOOL_ROUNDS
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Хватит"


def test_agent_answers_without_tools(monkeypatch):
    """Инструменты не нужны — ни одного вызова инструмента и ни одного стрима."""
    calls = {"stream": 0}

    monkeypatch.setattr(
        agent,
        "llm_complete",
        lambda *_a, **_kw: LlmResult(text="Привет!", model="fake", status="ok"),
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

    assert not [e for e in events if e["type"] == "tool"]
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Привет!"
    assert calls["stream"] == 0
