"""Дымовые тесты: проверяют, что каркас жив после правок.

Это то, что гоняет `make check`. Тесты намеренно грубые — их задача не покрыть
логику, а поймать «сломал и не заметил» за пару секунд.
"""

import json

from app.ai.tools import tool_aggregate_metrics, tool_create_record, tool_query_records
from app.auth import hash_password
from app.db import SessionLocal
from app.models import Asset, Event, User


def _seed_minimal() -> None:
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            db.add(User(email="demo@hackalem.kz", name="Демо", role="диспетчер", password_hash=hash_password("demo")))
        if db.query(Asset).count() == 0:
            db.add_all(
                Asset(
                    name=f"БелАЗ-75306 №{i}",
                    type="самосвал",
                    status="в работе" if i % 2 else "в ремонте",
                    site="Разрез «Восточный»",
                    engine_hours=1000.0 * i,
                    output_tonnes=900.0,
                )
                for i in range(1, 6)
            )
            db.flush()
        # Отдельная проверка: технику мог создать любой предыдущий тест, а событий
        # при этом не быть — тогда агрегаты по events вернут пусто.
        if db.query(Event).count() == 0:
            asset = db.query(Asset).first()
            db.add_all(
                Event(asset_id=asset.id, type="отказ", downtime_hours=6.0, comment="течь гидравлики")
                for _ in range(3)
            )
        db.commit()
    finally:
        db.close()


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_asset_crud(client):
    created = client.post(
        "/api/assets", json={"name": "Komatsu PC1250 №999", "type": "экскаватор", "engine_hours": 12000}
    )
    assert created.status_code == 201
    asset_id = created.json()["id"]

    assert client.get(f"/api/assets/{asset_id}").json()["name"] == "Komatsu PC1250 №999"
    assert any(row["id"] == asset_id for row in client.get("/api/assets").json())

    patched = client.patch(f"/api/assets/{asset_id}", json={"name": "Обновлено", "status": "в ремонте"})
    assert patched.json()["status"] == "в ремонте"

    assert client.delete(f"/api/assets/{asset_id}").status_code == 204
    assert client.get(f"/api/assets/{asset_id}").status_code == 404


def test_demo_auth(client):
    _seed_minimal()
    bad = client.post("/api/auth/login", json={"email": "demo@hackalem.kz", "password": "wrong"})
    assert bad.status_code == 401

    good = client.post("/api/auth/login", json={"email": "demo@hackalem.kz", "password": "demo"})
    assert good.status_code == 200
    token = good.json()["token"]

    assert client.get("/api/auth/me").status_code == 401
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == "demo@hackalem.kz"


def test_dashboard(client):
    _seed_minimal()
    data = client.get("/api/dashboard?days=30").json()
    assert [card["key"] for card in data["cards"]] == ["readiness", "downtime", "breakdowns", "output"]
    assert isinstance(data["timeseries"], list)


def test_ai_tools_work_without_api():
    """Инструменты — обычные функции над БД, модель для них не нужна."""
    _seed_minimal()
    db = SessionLocal()
    try:
        read = tool_query_records(db, table="assets", limit=3)
        assert read["count"] <= 3

        created = tool_create_record(db, table="assets", name="Из инструмента", engine_hours=500)
        assert created["created"] is True

        total = tool_aggregate_metrics(db, table="assets", metric="count", group_by="none")
        assert total["value"] >= 1

        downtime = tool_aggregate_metrics(
            db, table="events", metric="sum", field="downtime_hours", group_by="type"
        )
        assert downtime["groups"]
    finally:
        db.close()


def test_chat_falls_back_without_key(client):
    """Без OPENAI_API_KEY чат обязан отдать заглушку, а не 500."""
    response = client.post("/api/ai/chat", json={"message": "Сколько техники в ремонте?"})
    assert response.status_code == 200

    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    assert any(event["type"] == "delta" for event in events)
    done = [event for event in events if event["type"] == "done"]
    assert done and done[0]["meta"]["status"] == "fallback"


def test_structured_output_fallback_keeps_shape(client):
    """Даже без API structured output возвращает объект нужной формы."""
    response = client.post("/api/ai/classify", json={"text": "БелАЗ 112 встал, течь гидравлики, стоим третий час"})
    body = response.json()
    assert body["status"] == "fallback"
    assert set(body["data"]) == {"category", "unit", "urgency", "downtime_hours_estimate", "reason"}


def test_ai_metrics_logged(client):
    """Каждый вызов модели должен оказаться в ai_calls."""
    client.post("/api/ai/classify", json={"text": "тест"})
    metrics = client.get("/api/ai/metrics").json()
    assert metrics["total_calls"] >= 1
    assert metrics["recent"][0]["purpose"]


def test_root_serves_app_or_docs(client):
    """В деплое / отдаёт собранный фронт, без сборки — уводит на /docs.
    Оба варианта штатные: dist в .gitignore, на чистом клоне его нет."""
    from app.main import FRONTEND_DIST

    response = client.get("/", follow_redirects=False)
    if FRONTEND_DIST.is_dir():
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
    else:
        assert response.status_code in (302, 307)
        assert response.headers["location"] == "/docs"


def test_unknown_api_path_is_404(client):
    """Раздача фронта не должна проглатывать промахи по API: /api/* — всегда JSON."""
    assert client.get("/api/definitely-missing").status_code == 404


def test_reasoning_model_gets_effort_instead_of_temperature(monkeypatch):
    """gpt-5.x и gpt-6 отвечают 400 на temperature ≠ 1 — им уходит reasoning_effort.
    Цена считается и по имени со снапшотом: API возвращает «gpt-4o-mini-2024-07-18»."""
    from types import SimpleNamespace

    from app.ai import client as llm
    from app.config import settings

    sent: list[dict] = []

    def fake_create(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=100, total_tokens=1100),
            model=f"{kwargs['model']}-2026-09-01",
        )

    fake_openai = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    monkeypatch.setattr(llm, "_client", lambda: fake_openai)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "openai_reasoning_effort", "low")

    db = SessionLocal()
    try:
        monkeypatch.setattr(settings, "openai_model", "gpt-5.6-sol")
        sol = llm.complete(db, [{"role": "user", "content": "тест"}], temperature=0.2, use_cache=False)
        monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
        mini = llm.complete(db, [{"role": "user", "content": "тест"}], temperature=0.2, use_cache=False)
    finally:
        db.close()

    assert "temperature" not in sent[0] and sent[0]["reasoning_effort"] == "low"
    assert sent[1]["temperature"] == 0.2 and "reasoning_effort" not in sent[1]
    assert sol.status == mini.status == "ok"
    assert sol.cost_usd == 0.006  # 1000 токенов по $4 и 100 по $20 за миллион
    assert mini.cost_usd == 0.00021  # до правки имя со снапшотом давало $0
