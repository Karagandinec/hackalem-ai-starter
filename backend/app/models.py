"""Модели под трек «Добывающая промышленность».

Предметка: парк техники на разрезе/карьере и события с ней.
    Asset — единица техники: самосвал, экскаватор, буровой станок, конвейер.
    Event — что с ней произошло: отказ, простой, ТО, авария, нарушение ТБ.
    User  — сотрудник: механик, мастер участка, диспетчер.

Конкретный кейс внутри трека объявляют на площадке, поэтому поля намеренно
широкие. Если кейс окажется, скажем, про логистику руды — переименуй Asset
в Truck/Route прямо здесь и прогони `make seed`, миграций нет.

Разметка моделью (`ai_label`, `ai_score`) заточена под предиктивное
обслуживание: «риск отказа» и оценка от 0 до 1.
"""

from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    """Наивный UTC. SQLite не хранит таймзону, а смешивать aware/naive datetime —
    самый частый источник глупых багов, поэтому по всему проекту время naive-UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """Сотрудник. Авторизация демо-уровня, см. app/auth.py."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="механик")  # механик | мастер | диспетчер | админ
    password_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    assets: Mapped[list["Asset"]] = relationship(back_populates="owner")


class Asset(Base):
    """Единица техники на участке."""

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)  # бортовой номер: «БелАЗ-75306 №12»
    type: Mapped[str] = mapped_column(String(50), index=True)  # самосвал, экскаватор, буровой станок...
    status: Mapped[str] = mapped_column(String(50), index=True, default="в работе")
    brand: Mapped[str | None] = mapped_column(String(100), index=True, default=None)  # БелАЗ, Komatsu, Sandvik
    site: Mapped[str | None] = mapped_column(String(100), index=True, default=None)  # участок: разрез «Восточный»
    output_tonnes: Mapped[float] = mapped_column(Float, default=0.0)  # выработка за последнюю смену, тонн
    engine_hours: Mapped[float] = mapped_column(Float, default=0.0)  # наработка, моточасы
    description: Mapped[str | None] = mapped_column(Text, default=None)
    meta_json: Mapped[str | None] = mapped_column(Text, default=None)  # произвольный JSON строкой

    # Результат разметки моделью: POST /api/ai/enrich заполняет эти два поля.
    # Под этот трек — риск отказа: метка (низкий/средний/высокий) и оценка 0..1.
    ai_label: Mapped[str | None] = mapped_column(String(100), index=True, default=None)
    ai_score: Mapped[float | None] = mapped_column(Float, default=None)

    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)  # ответственный механик
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    owner: Mapped["User | None"] = relationship(back_populates="assets")
    events: Mapped[list["Event"]] = relationship(back_populates="asset", cascade="all, delete-orphan")


class Event(Base):
    """Событие с техникой: отказ, простой, ТО, авария, нарушение ТБ."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), index=True, default=None)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    type: Mapped[str] = mapped_column(String(50), index=True)  # отказ, простой, ТО, авария...
    status: Mapped[str] = mapped_column(String(50), default="закрыто")  # закрыто | в работе
    downtime_hours: Mapped[float] = mapped_column(Float, default=0.0)  # сколько часов техника стояла
    comment: Mapped[str | None] = mapped_column(Text, default=None)  # причина
    payload_json: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    asset: Mapped["Asset | None"] = relationship(back_populates="events")


class AiCall(Base):
    """Лог каждого обращения к модели: промпт, ответ, токены, латентность, цена."""

    __tablename__ = "ai_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    purpose: Mapped[str] = mapped_column(String(100), index=True, default="generic")
    model: Mapped[str] = mapped_column(String(100), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    response: Mapped[str] = mapped_column(Text, default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cached: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="ok", index=True)  # ok | error | fallback
    error: Mapped[str | None] = mapped_column(Text, default=None)
    tool_calls: Mapped[str | None] = mapped_column(Text, default=None)  # JSON-строка со списком вызовов


class AiCache(Base):
    """Кэш ответов модели, чтобы одинаковые запросы не тратили деньги дважды."""

    __tablename__ = "ai_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


Index("ix_assets_status_created", Asset.status, Asset.created_at)
Index("ix_events_type_created", Event.type, Event.created_at)
