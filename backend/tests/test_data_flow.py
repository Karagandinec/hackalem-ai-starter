"""Импорт CSV, выгрузка CSV и разметка записей моделью.

Это сценарий, который на хакатоне выполняется первым: залил файл -> разметил
моделью -> выгрузил результат. Ломается — демо показывать нечего.
"""

from app.db import SessionLocal
from app.models import Entity

CSV_RU = "Название;Город;Сумма;Статус\nАйгерим Сатпаева;Астана;15 000;new\nДанияр Ким;Караганда;8500,50;done\n"
CSV_EN = "name,city,amount\nJohn Smith,Astana,1000\n"


def _upload(client, content: str, filename: str = "data.csv"):
    return client.post(
        "/api/entities/import",
        files={"file": (filename, content.encode("utf-8"), "text/csv")},
    )


def test_import_russian_csv_with_semicolons(client):
    """Файл из русского Excel: `;` как разделитель, запятая в дробях, свои заголовки."""
    response = _upload(client, CSV_RU)
    assert response.status_code == 200

    body = response.json()
    assert body["imported"] == 2
    assert body["skipped"] == 0
    assert set(body["columns_used"]) == {"name", "city", "amount", "status"}

    db = SessionLocal()
    try:
        row = db.query(Entity).filter(Entity.name == "Данияр Ким").one()
        assert row.amount == 8500.5  # "8500,50" разобрано как число
        assert row.city == "Караганда"
        row_with_spaces = db.query(Entity).filter(Entity.name == "Айгерим Сатпаева").one()
        assert row_with_spaces.amount == 15000.0  # "15 000" тоже
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
    response = client.get("/api/entities/export.csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]

    text = response.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("id;name;type;status")
    assert "John Smith" in text


def test_enrich_writes_labels_back(client):
    """Без ключа разметка идёт заглушкой, но поля обязаны заполниться и сохраниться."""
    created = client.post("/api/entities", json={"name": "Запись для разметки", "type": "заявка"}).json()

    body = client.post("/api/ai/enrich", json={"entity_ids": [created["id"]], "limit": 1}).json()
    assert body["processed"] == 1
    assert body["status"] == "fallback"
    assert body["rows"][0]["id"] == created["id"]

    again = client.get(f"/api/entities/{created['id']}").json()
    assert again["ai_label"] is not None
    assert again["ai_score"] is not None


def test_enrich_respects_hard_limit(client):
    """Лимит записей за раз жёсткий: каждая запись — отдельный платный вызов."""
    body = client.post("/api/ai/enrich", json={"limit": 999}).json()
    assert body["processed"] <= 25
