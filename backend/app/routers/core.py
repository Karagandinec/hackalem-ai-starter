"""Базовые роуты: health-check, демо-логин, техника, события, дашборд.

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
from app.models import Asset, Event, User, utcnow
from app.schemas import (
    AssetIn,
    AssetOut,
    DashboardSummary,
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

# Что считаем поломкой, а не плановой остановкой. Правь под кейс.
BREAKDOWN_TYPES = ("отказ", "внеплановый ремонт", "авария")
# Техника, которая считается доступной для работы.
READY_STATUSES = ("в работе", "резерв")


# --- Health -----------------------------------------------------------------


@router.get("/health", tags=["health"])
def health(db: Session = Depends(get_db)) -> dict:
    """Живой ли сервер и видит ли он базу. Фронт дергает это при старте."""
    try:
        assets = db.scalar(select(func.count(Asset.id))) or 0
    except Exception as exc:  # noqa: BLE001 — health не должен падать, он должен рассказать
        return {"status": "degraded", "db": False, "error": str(exc), "ai_enabled": settings.ai_enabled}
    return {
        "status": "ok",
        "app": settings.app_name,
        "db": True,
        "assets": assets,
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


# --- Техника ----------------------------------------------------------------


def _filtered(
    date_from: str | None,
    date_to: str | None,
    status_filter: str | None,
    type_filter: str | None,
    site: str | None,
    search: str | None,
) -> Select:
    """Общий набор фильтров для списка и для выгрузки — чтобы они не разъехались."""
    stmt = select(Asset)
    if status_filter:
        stmt = stmt.where(Asset.status == status_filter)
    if type_filter:
        stmt = stmt.where(Asset.type == type_filter)
    if site:
        stmt = stmt.where(Asset.site == site)
    if search:
        stmt = stmt.where(Asset.name.ilike(f"%{search}%"))
    if date_from:
        stmt = stmt.where(Asset.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(Asset.created_at <= datetime.fromisoformat(date_to) + timedelta(days=1))
    return stmt.order_by(Asset.engine_hours.desc())


@router.get("/assets", response_model=list[AssetOut], tags=["assets"])
def list_assets(
    db: Session = Depends(get_db),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    status_filter: str | None = Query(None, alias="status"),
    type_filter: str | None = Query(None, alias="type"),
    site: str | None = None,
    search: str | None = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
) -> list[Asset]:
    """Список техники с фильтрами. Сортировка по наработке: самое изношенное сверху."""
    stmt = _filtered(date_from, date_to, status_filter, type_filter, site, search).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


@router.post("/assets", response_model=AssetOut, status_code=201, tags=["assets"])
def create_asset(payload: AssetIn, db: Session = Depends(get_db)) -> Asset:
    asset = Asset(**payload.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


# Колонки файла узнаём по этим синонимам: выгрузка из 1С или АСУ почти всегда
# приходит с русскими заголовками, и переименовывать их руками — потеря времени.
IMPORT_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "название", "наименование", "борт", "бортовой номер", "техника", "единица", "title"),
    "type": ("type", "тип", "вид", "тип техники"),
    "status": ("status", "статус", "состояние"),
    "brand": ("brand", "марка", "производитель", "модель"),
    "site": ("site", "участок", "объект", "разрез", "карьер", "площадка", "город"),
    "output_tonnes": ("output_tonnes", "выработка", "тонн", "тоннаж", "добыча"),
    "engine_hours": ("engine_hours", "наработка", "моточасы", "мч", "часы"),
    "description": ("description", "описание", "комментарий", "примечание", "comment"),
}
NUMERIC_FIELDS = ("output_tonnes", "engine_hours")


@router.post("/assets/import", response_model=ImportResult, tags=["assets"])
async def import_assets(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportResult:
    """Загрузка CSV с техникой.

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
            errors=[f"Не нашёл колонку с названием техники. Заголовки файла: {reader.fieldnames}"],
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
                if field in NUMERIC_FIELDS:
                    payload[field] = float(value.replace(" ", "").replace(",", "."))
                else:
                    payload[field] = value
            if not payload.get("name"):
                skipped += 1
                continue
            payload.setdefault("type", "не указан")
            payload.setdefault("status", "в работе")
            db.add(Asset(**payload))
            imported += 1
        except (ValueError, TypeError) as exc:
            skipped += 1
            if len(errors) < 10:  # 10 примеров достаточно, весь файл в ответ не тащим
                errors.append(f"строка {line}: {exc}")

    db.commit()
    return ImportResult(imported=imported, skipped=skipped, errors=errors, columns_used=sorted(set(mapping.values())))


@router.get("/assets/export.csv", tags=["assets"])
def export_assets(
    db: Session = Depends(get_db),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    status_filter: str | None = Query(None, alias="status"),
    type_filter: str | None = Query(None, alias="type"),
    site: str | None = None,
    search: str | None = None,
    limit: int = Query(5000, le=50000),
) -> StreamingResponse:
    """Выгрузка отфильтрованной техники в CSV — те же фильтры, что у списка."""
    rows = db.scalars(_filtered(date_from, date_to, status_filter, type_filter, site, search).limit(limit)).all()

    buffer = io.StringIO()
    # BOM и `;` — чтобы файл открывался в русском Excel двойным щелчком, без танцев.
    buffer.write("﻿")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(
        ["id", "техника", "тип", "статус", "марка", "участок", "выработка_т", "наработка_мч", "риск", "оценка"]
    )
    for row in rows:
        writer.writerow([
            row.id, row.name, row.type, row.status, row.brand or "", row.site or "",
            row.output_tonnes, row.engine_hours, row.ai_label or "",
            row.ai_score if row.ai_score is not None else "",
        ])
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="assets.csv"'},
    )


@router.get("/assets/{asset_id}", response_model=AssetOut, tags=["assets"])
def get_asset(asset_id: int, db: Session = Depends(get_db)) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    return asset


@router.patch("/assets/{asset_id}", response_model=AssetOut, tags=["assets"])
def update_asset(asset_id: int, payload: AssetIn, db: Session = Depends(get_db)) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(asset, key, value)
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/assets/{asset_id}", status_code=204, tags=["assets"])
def delete_asset(asset_id: int, db: Session = Depends(get_db)) -> None:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    db.delete(asset)
    db.commit()


# --- События ----------------------------------------------------------------


@router.get("/events", response_model=list[EventOut], tags=["events"])
def list_events(
    db: Session = Depends(get_db),
    asset_id: int | None = None,
    type_filter: str | None = Query(None, alias="type"),
    limit: int = Query(100, le=1000),
) -> list[Event]:
    stmt = select(Event)
    if asset_id:
        stmt = stmt.where(Event.asset_id == asset_id)
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
    """4 карточки-метрики + ряд для графика простоев. Меняй под свой кейс здесь."""
    now = utcnow()
    period_start = now - timedelta(days=days)
    prev_start = period_start - timedelta(days=days)

    def downtime_between(start: datetime, end: datetime) -> float:
        return float(
            db.scalar(
                select(func.coalesce(func.sum(Event.downtime_hours), 0.0)).where(
                    Event.created_at >= start, Event.created_at < end
                )
            )
            or 0.0
        )

    def breakdowns_between(start: datetime, end: datetime) -> int:
        return db.scalar(
            select(func.count(Event.id)).where(
                Event.created_at >= start, Event.created_at < end, Event.type.in_(BREAKDOWN_TYPES)
            )
        ) or 0

    fleet_total = db.scalar(select(func.count(Asset.id))) or 0
    fleet_ready = db.scalar(select(func.count(Asset.id)).where(Asset.status.in_(READY_STATUSES))) or 0
    output_now = float(db.scalar(select(func.coalesce(func.sum(Asset.output_tonnes), 0.0))) or 0.0)

    downtime_now, downtime_prev = downtime_between(period_start, now), downtime_between(prev_start, period_start)
    breakdowns_now, breakdowns_prev = breakdowns_between(period_start, now), breakdowns_between(prev_start, period_start)

    def delta(current: float, previous: float) -> float | None:
        if not previous:
            return None
        return round((current - previous) / previous * 100, 1)

    cards = [
        MetricCard(
            key="readiness",
            label="Техника на ходу",
            value=round(fleet_ready / fleet_total * 100, 1) if fleet_total else 0.0,
            unit="%",
        ),
        MetricCard(
            key="downtime",
            label="Простои за период",
            value=round(downtime_now),
            unit="ч",
            delta_pct=delta(downtime_now, downtime_prev),
            lower_is_better=True,
        ),
        MetricCard(
            key="breakdowns",
            label="Отказов и аварий",
            value=breakdowns_now,
            delta_pct=delta(breakdowns_now, breakdowns_prev),
            lower_is_better=True,
        ),
        MetricCard(key="output", label="Выработка за смену", value=round(output_now), unit="т"),
    ]

    rows = db.execute(
        select(
            func.strftime("%Y-%m-%d", Event.created_at).label("day"),
            func.coalesce(func.sum(Event.downtime_hours), 0.0),
            func.count(Event.id),
        )
        .where(Event.created_at >= period_start)
        .group_by("day")
        .order_by("day")
    ).all()

    timeseries = [
        TimeseriesPoint(date=day, downtime_hours=round(float(hours), 1), events=count) for day, hours, count in rows
    ]
    return DashboardSummary(cards=cards, timeseries=timeseries)
