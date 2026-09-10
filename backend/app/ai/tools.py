"""Три инструмента для function calling: чтение из БД, запись в БД, агрегат.

Как добавить свой инструмент:
  1) описать его в TOOL_DEFINITIONS (JSON Schema аргументов);
  2) написать функцию tool_<имя>(db, **args) -> dict;
  3) добавить её в TOOL_HANDLERS.
Больше ничего трогать не нужно — агент подхватит автоматически.

Всё, что возвращает инструмент, уходит обратно в модель как текст, поэтому
возвращаем компактный JSON-совместимый dict и режем размер (LIMIT_MAX).
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Entity, Event

LIMIT_MAX = 50  # столько строк максимум отдаём модели, чтобы не жечь токены

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_records",
            "description": (
                "Прочитать записи из базы: список сущностей (entities) или событий (events) "
                "с фильтрами по статусу, типу, категории, городу и датам. "
                "Используй, когда нужны конкретные строки, а не цифра."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "enum": ["entities", "events"]},
                    "status": {"type": "string", "description": "Фильтр по статусу, например new/done"},
                    "type": {"type": "string", "description": "Фильтр по типу"},
                    "category": {"type": "string"},
                    "city": {"type": "string"},
                    "search": {"type": "string", "description": "Подстрока в названии (только entities)"},
                    "date_from": {"type": "string", "description": "Дата с, YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "Дата по, YYYY-MM-DD"},
                    "limit": {"type": "integer", "description": f"Сколько строк вернуть, максимум {LIMIT_MAX}"},
                },
                "required": ["table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_record",
            "description": (
                "Создать новую запись в базе (entities или events). "
                "Вызывай только когда пользователь явно просит что-то создать/добавить/записать."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "enum": ["entities", "events"]},
                    "name": {"type": "string", "description": "Название (для entities обязательно)"},
                    "type": {"type": "string"},
                    "status": {"type": "string"},
                    "category": {"type": "string"},
                    "city": {"type": "string"},
                    "amount": {"type": "number", "description": "Сумма (entities)"},
                    "value": {"type": "number", "description": "Значение (events)"},
                    "entity_id": {"type": "integer", "description": "К какой сущности относится событие"},
                    "comment": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate_metrics",
            "description": (
                "Посчитать агрегат по базе: количество, сумму или среднее, "
                "с группировкой по статусу/типу/категории/городу/дню. "
                "Используй для вопросов вида 'сколько', 'на какую сумму', 'какой средний чек', 'динамика по дням'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "enum": ["entities", "events"]},
                    "metric": {"type": "string", "enum": ["count", "sum", "avg"]},
                    "group_by": {
                        "type": "string",
                        "enum": ["none", "status", "type", "category", "city", "day"],
                        "description": "По чему группировать; none — одно общее число",
                    },
                    "date_from": {"type": "string", "description": "Дата с, YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "Дата по, YYYY-MM-DD"},
                },
                "required": ["table", "metric"],
            },
        },
    },
]


def _model_for(table: str):
    if table == "entities":
        return Entity
    if table == "events":
        return Event
    raise ValueError(f"Неизвестная таблица: {table}. Доступны: entities, events")


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _row_to_dict(row) -> dict:
    """Строка ORM -> плоский dict без служебных полей SQLAlchemy."""
    out = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        out[column.name] = value.isoformat(sep=" ", timespec="seconds") if isinstance(value, datetime) else value
    out.pop("meta_json", None)
    out.pop("payload_json", None)
    return out


# --- 1. Чтение --------------------------------------------------------------


def tool_query_records(db: Session, **args) -> dict:
    model = _model_for(args.get("table", "entities"))
    stmt = select(model)

    for field_name in ("status", "type", "category", "city"):
        value = args.get(field_name)
        if value and hasattr(model, field_name):
            stmt = stmt.where(getattr(model, field_name) == value)

    if args.get("search") and hasattr(model, "name"):
        stmt = stmt.where(model.name.ilike(f"%{args['search']}%"))

    date_from = _parse_date(args.get("date_from"))
    date_to = _parse_date(args.get("date_to"))
    if date_from:
        stmt = stmt.where(model.created_at >= date_from)
    if date_to:
        stmt = stmt.where(model.created_at <= date_to.replace(hour=23, minute=59, second=59))

    limit = min(int(args.get("limit") or 20), LIMIT_MAX)
    rows = db.execute(stmt.order_by(model.created_at.desc()).limit(limit)).scalars().all()
    return {"table": args.get("table"), "count": len(rows), "rows": [_row_to_dict(r) for r in rows]}


# --- 2. Запись --------------------------------------------------------------


def tool_create_record(db: Session, **args) -> dict:
    table = args.get("table", "entities")
    model = _model_for(table)
    allowed = {c.name for c in model.__table__.columns} - {"id", "created_at"}
    payload = {k: v for k, v in args.items() if k in allowed and v is not None}

    if table == "entities":
        payload.setdefault("name", "Без названия")
        payload.setdefault("type", "generic")
    else:
        payload.setdefault("type", "note")

    row = model(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"created": True, "table": table, "row": _row_to_dict(row)}


# --- 3. Агрегат -------------------------------------------------------------


def tool_aggregate_metrics(db: Session, **args) -> dict:
    table = args.get("table", "entities")
    model = _model_for(table)
    metric = args.get("metric", "count")
    group_by = args.get("group_by", "none")

    value_column = model.amount if table == "entities" else model.value
    agg = {
        "count": func.count(model.id),
        "sum": func.coalesce(func.sum(value_column), 0.0),
        "avg": func.coalesce(func.avg(value_column), 0.0),
    }.get(metric)
    if agg is None:
        raise ValueError(f"Неизвестная метрика: {metric}. Доступны: count, sum, avg")

    if group_by == "day":
        group_column = func.strftime("%Y-%m-%d", model.created_at)
    elif group_by in ("status", "type", "category", "city") and hasattr(model, group_by):
        group_column = getattr(model, group_by)
    else:
        group_column = None

    stmt = select(group_column, agg) if group_column is not None else select(agg)

    date_from = _parse_date(args.get("date_from"))
    date_to = _parse_date(args.get("date_to"))
    if date_from:
        stmt = stmt.where(model.created_at >= date_from)
    if date_to:
        stmt = stmt.where(model.created_at <= date_to.replace(hour=23, minute=59, second=59))

    if group_column is not None:
        stmt = stmt.group_by(group_column).order_by(group_column)
        rows = db.execute(stmt).all()
        groups = [{"key": str(key), "value": round(float(val or 0), 2)} for key, val in rows[:LIMIT_MAX]]
        return {"table": table, "metric": metric, "group_by": group_by, "groups": groups}

    value = db.execute(stmt).scalar_one()
    return {"table": table, "metric": metric, "group_by": "none", "value": round(float(value or 0), 2)}


TOOL_HANDLERS = {
    "query_records": tool_query_records,
    "create_record": tool_create_record,
    "aggregate_metrics": tool_aggregate_metrics,
}


def run_tool(db: Session, name: str, arguments: str | dict) -> dict:
    """Выполняет инструмент по имени. Ошибку не поднимает наверх, а возвращает
    модели как результат — та обычно исправляется и пробует ещё раз."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {"error": f"Неизвестный инструмент: {name}"}
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
    except json.JSONDecodeError as exc:
        return {"error": f"Аргументы не разобрались как JSON: {exc}"}
    try:
        return handler(db, **args)
    except Exception as exc:  # noqa: BLE001 — модель должна увидеть текст ошибки
        db.rollback()
        return {"error": f"{type(exc).__name__}: {exc}"}
