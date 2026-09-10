"""Три универсальные модели под переименование + служебные таблицы AI.

Идея: кейс хакатона заранее неизвестен, поэтому модели намеренно общие.
Когда кейс объявят — переименуй прямо здесь:
    Entity -> Order / Patient / Property / Vacancy ...
    Event  -> Delivery / Visit / Viewing / Interview ...
Поля name/type/status/category/amount/meta_json подходят почти под любой кейс,
лишнее удаляй, недостающее добавляй. Миграций нет — просто `make seed` заново.
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
    """Пользователь. Авторизация демо-уровня, см. app/auth.py."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="user")  # user | manager | admin
    password_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    entities: Mapped[list["Entity"]] = relationship(back_populates="owner")


class Entity(Base):
    """Главный объект предметной области: заказ, заявка, объект, клиент..."""

    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True, default="new")
    category: Mapped[str | None] = mapped_column(String(100), index=True, default=None)
    city: Mapped[str | None] = mapped_column(String(100), default=None)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    meta_json: Mapped[str | None] = mapped_column(Text, default=None)  # произвольный JSON строкой
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    owner: Mapped["User | None"] = relationship(back_populates="entities")
    events: Mapped[list["Event"]] = relationship(back_populates="entity", cascade="all, delete-orphan")


class Event(Base):
    """Что произошло с Entity: смена статуса, доставка, визит, платёж..."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id"), index=True, default=None)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(50), default="done")
    value: Mapped[float] = mapped_column(Float, default=0.0)
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    payload_json: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    entity: Mapped["Entity | None"] = relationship(back_populates="events")


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


Index("ix_entities_status_created", Entity.status, Entity.created_at)
Index("ix_events_type_created", Event.type, Event.created_at)
