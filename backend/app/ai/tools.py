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

from app.models import Asset, Event

LIMIT_MAX = 50  # столько строк максимум отдаём модели, чтобы не жечь токены

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_records",
            "description": (
                "Прочитать записи из базы: список техники (assets) или событий с ней (events) "
                "с фильтрами по статусу, типу, участку и датам. "
                "Используй, когда нужны конкретные единицы техники или конкретные отказы, а не цифра. "
                "Чтобы посмотреть историю одной машины, передай asset_id при table=events."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "enum": ["assets", "events"]},
                    "status": {"type": "string", "description": "в работе / в ремонте / ТО / простой / резерв"},
                    "type": {
                        "type": "string",
                        "description": "для assets — самосвал, экскаватор...; для events — отказ, плановое ТО...",
                    },
                    "site": {"type": "string", "description": "участок, например Разрез «Восточный» (только assets)"},
                    "asset_id": {"type": "integer", "description": "история конкретной единицы техники (events)"},
                    "search": {"type": "string", "description": "подстрока в названии техники (только assets)"},
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
                "Создать новую запись: единицу техники (assets) или событие с ней (events). "
                "Вызывай только когда пользователь прямо просит что-то создать или зафиксировать: "
                "«заведи отказ», «запиши простой», «добавь самосвал»."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "enum": ["assets", "events"]},
                    "name": {"type": "string", "description": "бортовой номер или название (assets, обязательно)"},
                    "type": {"type": "string"},
                    "status": {"type": "string"},
                    "brand": {"type": "string"},
                    "site": {"type": "string"},
                    "output_tonnes": {"type": "number", "description": "выработка за смену, тонн (assets)"},
                    "engine_hours": {"type": "number", "description": "наработка, моточасы (assets)"},
                    "downtime_hours": {"type": "number", "description": "часы простоя (events)"},
                    "asset_id": {"type": "integer", "description": "к какой технике относится событие"},
                    "comment": {"type": "string", "description": "причина (events)"},
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
                "Посчитать агрегат: количество, сумму или среднее, с группировкой по статусу, типу, "
                "марке, участку или дню. Используй для «сколько простоев», «какая техника чаще ломается», "
                "«сколько часов потеряли по участкам», «динамика по дням», «средняя наработка»."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "enum": ["assets", "events"]},
                    "metric": {"type": "string", "enum": ["count", "sum", "avg"]},
                    "field": {
                        "type": "string",
                        "enum": ["downtime_hours", "output_tonnes", "engine_hours"],
                        "description": "что суммировать или усреднять; для count не нужно",
                    },
                    "group_by": {
                        "type": "string",
                        "enum": ["none", "status", "type", "brand", "site", "day", "asset"],
                        "description": "по чему группировать; none — одно общее число",
                    },
                    "date_from": {"type": "string", "description": "Дата с, YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "Дата по, YYYY-MM-DD"},
                },
                "required": ["table", "metric"],
            },
        },
    },
]

DEFAULT_VALUE_FIELD = {"assets": "output_tonnes", "events": "downtime_hours"}


def _model_for(table: str):
    if table == "assets":
        return Asset
    if table == "events":
        return Event
    raise ValueError(f"Неизвестная таблица: {table}. Доступны: assets, events")


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
    table = args.get("table", "assets")
    model = _model_for(table)
    stmt = select(model)

    for field_name in ("status", "type", "site", "asset_id"):
        value = args.get(field_name)
        if value not in (None, "") and hasattr(model, field_name):
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
    # Технику показываем от самой изношенной, события — от самых свежих.
    order = model.engine_hours.desc() if table == "assets" else model.created_at.desc()
    rows = db.execute(stmt.order_by(order).limit(limit)).scalars().all()
    return {"table": table, "count": len(rows), "rows": [_row_to_dict(r) for r in rows]}


# --- 2. Запись --------------------------------------------------------------


def tool_create_record(db: Session, **args) -> dict:
    table = args.get("table", "assets")
    model = _model_for(table)
    allowed = {c.name for c in model.__table__.columns} - {"id", "created_at"}
    payload = {k: v for k, v in args.items() if k in allowed and v is not None}

    if table == "assets":
        payload.setdefault("name", "Без названия")
        payload.setdefault("type", "не указан")
        payload.setdefault("status", "в работе")
    else:
        payload.setdefault("type", "отказ")

    row = model(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"created": True, "table": table, "row": _row_to_dict(row)}


# --- 3. Агрегат -------------------------------------------------------------


def tool_aggregate_metrics(db: Session, **args) -> dict:
    table = args.get("table", "events")
    model = _model_for(table)
    metric = args.get("metric", "count")
    group_by = args.get("group_by", "none")

    field = args.get("field") or DEFAULT_VALUE_FIELD[table]
    if not hasattr(model, field):
        raise ValueError(f"У таблицы {table} нет поля {field}")
    value_column = getattr(model, field)

    agg = {
        "count": func.count(model.id),
        "sum": func.coalesce(func.sum(value_column), 0.0),
        "avg": func.coalesce(func.avg(value_column), 0.0),
    }.get(metric)
    if agg is None:
        raise ValueError(f"Неизвестная метрика: {metric}. Доступны: count, sum, avg")

    if group_by == "day":
        group_column = func.strftime("%Y-%m-%d", model.created_at)
    elif group_by == "asset":
        group_column = model.asset_id if table == "events" else model.name
    elif group_by in ("status", "type", "brand", "site") and hasattr(model, group_by):
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
        # Группы сортируем по значению: сверху то, где больнее всего.
        stmt = stmt.group_by(group_column).order_by(agg.desc())
        rows = db.execute(stmt).all()
        groups = [{"key": str(key), "value": round(float(val or 0), 2)} for key, val in rows[:LIMIT_MAX]]
        return {"table": table, "metric": metric, "field": field, "group_by": group_by, "groups": groups}

    value = db.execute(stmt).scalar_one()
    return {"table": table, "metric": metric, "field": field, "group_by": "none", "value": round(float(value or 0), 2)}


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
