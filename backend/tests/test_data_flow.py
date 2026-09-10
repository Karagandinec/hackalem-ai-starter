"""Импорт CSV, выгрузка CSV и разметка техники моделью.

Это сценарий, который на хакатоне выполняется первым: залил парк техники ->
оценил риск отказа моделью -> выгрузил результат. Ломается — демо показывать нечего.
"""

from app.db import SessionLocal
from app.models import Asset

CSV_RU = (
    "Бортовой номер;Тип;Участок;Наработка;Статус\n"
    "БелАЗ-75306 №201;самосвал;Разрез «Восточный»;12 500;в работе\n"
    "Komatsu PC1250 №14;экскаватор;Разрез «Северный»;18300,5;в ремонте\n"
)
CSV_EN = "name,type,engine_hours\nCaterpillar 777 #7,самосвал,4200\n"


def _upload(client, content: str, filename: str = "fleet.csv"):
    return client.post(
        "/api/assets/import",
        files={"file": (filename, content.encode("utf-8"), "text/csv")},
    )


def test_import_russian_csv_with_semicolons(client):
    """Файл из русского Excel: `;` как разделитель, запятая в дробях, свои заголовки."""
    response = _upload(client, CSV_RU)
    assert response.status_code == 200

    body = response.json()
    assert body["imported"] == 2
    assert body["skipped"] == 0
    assert set(body["columns_used"]) == {"name", "type", "site", "engine_hours", "status"}

    db = SessionLocal()
    try:
        row = db.query(Asset).filter(Asset.name == "Komatsu PC1250 №14").one()
        assert row.engine_hours == 18300.5  # "18300,5" разобрано как число
        assert row.site == "Разрез «Северный»"
        spaced = db.query(Asset).filter(Asset.name == "БелАЗ-75306 №201").one()
        assert spaced.engine_hours == 12500.0  # "12 500" тоже
    finally:
        db.close()


def test_import_plain_english_csv(client):
    body = _upload(client, CSV_EN).json()
    assert body["imported"] == 1


def test_import_without_name_column_explains_itself(client):
    """Не угадали колонку — объясняем, что видели, а не молчим."""
    body = _upload(client, "col_a,col_b\n1,2\n").json()
    assert body["imported"] == 0
    assert "col_a" in body["errors"][0]


def test_import_empty_file(client):
    assert _upload(client, "").json()["errors"] == ["Файл пустой"]


def test_export_csv(client):
    _upload(client, CSV_EN)
    response = client.get("/api/assets/export.csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]

    text = response.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("id;техника;тип;статус")
    assert "Caterpillar 777 #7" in text


def test_enrich_writes_risk_back(client):
    """Без ключа разметка идёт заглушкой, но поля риска обязаны заполниться и сохраниться."""
    created = client.post("/api/assets", json={"name": "БелАЗ для разметки", "type": "самосвал"}).json()

    body = client.post("/api/ai/enrich", json={"asset_ids": [created["id"]], "limit": 1}).json()
    assert body["processed"] == 1
    assert body["status"] == "fallback"
    assert body["rows"][0]["id"] == created["id"]

    again = client.get(f"/api/assets/{created['id']}").json()
    assert again["ai_label"] is not None
    assert again["ai_score"] is not None


def test_enrich_respects_hard_limit(client):
    """Лимит за раз жёсткий: каждая единица техники — отдельный платный вызов."""
    body = client.post("/api/ai/enrich", json={"limit": 999}).json()
    assert body["processed"] <= 25
