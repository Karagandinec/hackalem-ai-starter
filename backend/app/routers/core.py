"""Базовые роуты: health-check, демо-логин, CRUD сущностей и событий.

Всё, что нужно, чтобы фронт ожил сразу после `make seed`.
"""

import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user, hash_password, make_token
from app.config import settings
from app.db import get_db
from app.models import Entity, Event, User, utcnow
from app.schemas import (
    DashboardSummary,
    EntityIn,
    EntityOut,
    EventIn,
    EventOut,
    ImportResult,
    LoginIn,
    LoginOut,
    MetricCard,
    TimeseriesPoint,
    UserOut,
)

router = APIRouter()


# --- Health -----------------------------------------------------------------


@router.get("/health", tags=["health"])
def health(db: Session = Depends(get_db)) -> dict:
    """Живой ли сервер и видит ли он базу. Фронт дергает это при старте."""
    try:
        entities = db.scalar(select(func.count(Entity.id))) or 0
        db_ok = True
    except Exception as exc:  # noqa: BLE001 — health не должен падать, он должен рассказать
        entities, db_ok = 0, False
        return {"status": "degraded", "db": db_ok, "error": str(exc), "ai_enabled": settings.ai_enabled}
    return {
        "status": "ok",
        "app": settings.app_name,
        "db": db_ok,
        "entities": entities,
        "ai_enabled": settings.ai_enabled,  # False = работаем на заглушке
        "model": settings.openai_model,
        "time": utcnow().isoformat(timespec="seconds"),
    }


# --- Демо-авторизация -------------------------------------------------------


@router.post("/auth/login", response_model=LoginOut, tags=["auth"])
def login(payload: LoginIn, db: Session = Depends(get_db)) -> LoginOut:
    """Демо-логин. Пароли из seed: demo@hackalem.kz / demo (см. scripts/seed.py)."""
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if user is None or user.password_hash != hash_password(payload.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")
    return LoginOut(token=make_token(user), user=UserOut.model_validate(user))


@router.get("/auth/me", response_model=UserOut, tags=["auth"])
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/users", response_model=list[UserOut], tags=["auth"])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)).all())


# --- Entities ---------------------------------------------------------------


def _filtered(
    date_from: str | None,
    date_to: str | None,
    status_filter: str | None,
    type_filter: str | None,
    search: str | None,
) -> Select:
    """Общий набор фильтров для списка и для выгрузки — чтобы они не разъехались."""
    stmt = select(Entity)
    if status_filter:
        stmt = stmt.where(Entity.status == status_filter)
    if type_filter:
        stmt = stmt.where(Entity.type == type_filter)
    if search:
        stmt = stmt.where(Entity.name.ilike(f"%{search}%"))
    if date_from:
        stmt = stmt.where(Entity.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(Entity.created_at <= datetime.fromisoformat(date_to) + timedelta(days=1))
    return stmt.order_by(Entity.created_at.desc())


@router.get("/entities", response_model=list[EntityOut], tags=["entities"])
def list_entities(
    db: Session = Depends(get_db),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    status_filter: str | None = Query(None, alias="status"),
    type_filter: str | None = Query(None, alias="type"),
    search: str | None = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
) -> list[Entity]:
    """Список с фильтрами — под таблицу на дашборде."""
    stmt = _filtered(date_from, date_to, status_filter, type_filter, search).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


@router.post("/entities", response_model=EntityOut, status_code=201, tags=["entities"])
def create_entity(payload: EntityIn, db: Session = Depends(get_db)) -> Entity:
    entity = Entity(**payload.model_dump())
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


# Колонки файла узнаём по этим синонимам: датасет на хакатоне почти всегда
# приходит с русскими заголовками, и переименовывать их руками — потеря времени.
IMPORT_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "название", "наименование", "имя", "клиент", "title"),
    "type": ("type", "тип", "вид"),
    "status": ("status", "статус", "состояние"),
    "category": ("category", "категория", "группа"),
    "city": ("city", "город", "регион"),
    "amount": ("amount", "сумма", "цена", "стоимость", "price", "total"),
    "description": ("description", "описание", "комментарий", "примечание", "comment"),
}


@router.post("/entities/import", response_model=ImportResult, tags=["entities"])
async def import_entities(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportResult:
    """Загрузка CSV в таблицу entities.

    Умеет то, обо что обычно спотыкаются в спешке: BOM от Excel, разделитель `;`
    вместо запятой и русские заголовки колонок. Неизвестные колонки игнорируются,
    испорченные строки не роняют импорт, а попадают в errors.
    """
    raw = await file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    if not text.strip():
        return ImportResult(imported=0, skipped=0, errors=["Файл пустой"], columns_used=[])

    # Excel в русской локали сохраняет CSV через точку с запятой.
    header = text.splitlines()[0]
    delimiter = ";" if header.count(";") > header.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    mapping: dict[str, str] = {}
    for column in reader.fieldnames or []:
        key = (column or "").strip().lower()
        for field, aliases in IMPORT_ALIASES.items():
            if key in aliases and field not in mapping.values():
                mapping[column] = field
                break

    if "name" not in mapping.values():
        return ImportResult(
            imported=0,
            skipped=0,
            errors=[f"Не нашёл колонку с названием. Заголовки файла: {reader.fieldnames}"],
            columns_used=[],
        )

    imported, skipped, errors = 0, 0, []
    for line, row in enumerate(reader, start=2):
        payload: dict = {}
        try:
            for column, field in mapping.items():
                value = (row.get(column) or "").strip()
                if not value:
                    continue
                payload[field] = float(value.replace(" ", "").replace(",", ".")) if field == "amount" else value
            if not payload.get("name"):
                skipped += 1
                continue
            payload.setdefault("type", "imported")
            payload.setdefault("status", "new")
            db.add(Entity(**payload))
            imported += 1
        except (ValueError, TypeError) as exc:
            skipped += 1
            if len(errors) < 10:  # 10 примеров достаточно, весь файл в ответ не тащим
                errors.append(f"строка {line}: {exc}")

    db.commit()
    return ImportResult(imported=imported, skipped=skipped, errors=errors, columns_used=sorted(set(mapping.values())))


@router.get("/entities/export.csv", tags=["entities"])
def export_entities(
    db: Session = Depends(get_db),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    status_filter: str | None = Query(None, alias="status"),
    type_filter: str | None = Query(None, alias="type"),
    search: str | None = None,
    limit: int = Query(5000, le=50000),
) -> StreamingResponse:
    """Выгрузка отфильтрованных записей в CSV — те же фильтры, что у списка."""
    rows = db.scalars(_filtered(date_from, date_to, status_filter, type_filter, search).limit(limit)).all()

    buffer = io.StringIO()
    # BOM и `;` — чтобы файл открывался в русском Excel двойным щелчком, без танцев.
    buffer.write("\ufeff")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(["id", "name", "type", "status", "category", "city", "amount", "ai_label", "ai_score", "created_at"])
    for row in rows:
        writer.writerow([
            row.id, row.name, row.type, row.status, row.category or "", row.city or "",
            row.amount, row.ai_label or "", row.ai_score if row.ai_score is not None else "",
            row.created_at.isoformat(sep=" ", timespec="seconds"),
        ])
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="entities.csv"'},
    )


@router.get("/entities/{entity_id}", response_model=EntityOut, tags=["entities"])
def get_entity(entity_id: int, db: Session = Depends(get_db)) -> Entity:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    return entity


@router.patch("/entities/{entity_id}", response_model=EntityOut, tags=["entities"])
def update_entity(entity_id: int, payload: EntityIn, db: Session = Depends(get_db)) -> Entity:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(entity, key, value)
    db.commit()
    db.refresh(entity)
    return entity


@router.delete("/entities/{entity_id}", status_code=204, tags=["entities"])
def delete_entity(entity_id: int, db: Session = Depends(get_db)) -> None:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    db.delete(entity)
    db.commit()


# --- Events -----------------------------------------------------------------


@router.get("/events", response_model=list[EventOut], tags=["events"])
def list_events(
    db: Session = Depends(get_db),
    entity_id: int | None = None,
    type_filter: str | None = Query(None, alias="type"),
    limit: int = Query(100, le=1000),
) -> list[Event]:
    stmt = select(Event)
    if entity_id:
        stmt = stmt.where(Event.entity_id == entity_id)
    if type_filter:
        stmt = stmt.where(Event.type == type_filter)
    return list(db.scalars(stmt.order_by(Event.created_at.desc()).limit(limit)).all())


@router.post("/events", response_model=EventOut, status_code=201, tags=["events"])
def create_event(payload: EventIn, db: Session = Depends(get_db)) -> Event:
    event = Event(**payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


# --- Дашборд ----------------------------------------------------------------


@router.get("/dashboard", response_model=DashboardSummary, tags=["dashboard"])
def dashboard(db: Session = Depends(get_db), days: int = Query(30, ge=1, le=365)) -> DashboardSummary:
    """4 карточки-метрики + ряд для графика. Меняй под свой кейс прямо здесь."""
    now = utcnow()
    period_start = now - timedelta(days=days)
    prev_start = period_start - timedelta(days=days)

    def count_between(start: datetime, end: datetime) -> int:
        return db.scalar(
            select(func.count(Entity.id)).where(Entity.created_at >= start, Entity.created_at < end)
        ) or 0

    def sum_between(start: datetime, end: datetime) -> float:
        return float(
            db.scalar(
                select(func.coalesce(func.sum(Entity.amount), 0.0)).where(
                    Entity.created_at >= start, Entity.created_at < end
                )
            )
            or 0.0
        )

    current_count = count_between(period_start, now)
    previous_count = count_between(prev_start, period_start)
    current_sum = sum_between(period_start, now)
    previous_sum = sum_between(prev_start, period_start)
    done_count = db.scalar(
        select(func.count(Entity.id)).where(Entity.created_at >= period_start, Entity.status == "done")
    ) or 0
    events_count = db.scalar(select(func.count(Event.id)).where(Event.created_at >= period_start)) or 0

    def delta(current: float, previous: float) -> float | None:
        if not previous:
            return None
        return round((current - previous) / previous * 100, 1)

    cards = [
        MetricCard(key="entities", label="Записей за период", value=current_count, delta_pct=delta(current_count, previous_count)),
        MetricCard(key="amount", label="Сумма", value=round(current_sum), unit="₸", delta_pct=delta(current_sum, previous_sum)),
        MetricCard(
            key="conversion",
            label="Доля закрытых",
            value=round(done_count / current_count * 100, 1) if current_count else 0.0,
            unit="%",
        ),
        MetricCard(key="events", label="Событий", value=events_count),
    ]

    rows = db.execute(
        select(
            func.strftime("%Y-%m-%d", Entity.created_at).label("day"),
            func.count(Entity.id),
            func.coalesce(func.sum(Entity.amount), 0.0),
        )
        .where(Entity.created_at >= period_start)
        .group_by("day")
        .order_by("day")
    ).all()

    timeseries = [TimeseriesPoint(date=day, count=count, amount=round(float(amount), 2)) for day, count, amount in rows]
    return DashboardSummary(cards=cards, timeseries=timeseries)
