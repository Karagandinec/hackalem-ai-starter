"""Базовые роуты: health-check, демо-логин, CRUD сущностей и событий.

Всё, что нужно, чтобы фронт ожил сразу после `make seed`.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
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
    stmt = stmt.order_by(Entity.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


@router.post("/entities", response_model=EntityOut, status_code=201, tags=["entities"])
def create_entity(payload: EntityIn, db: Session = Depends(get_db)) -> Entity:
    entity = Entity(**payload.model_dump())
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


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
