"""Pydantic-схемы запросов и ответов. Переименовывай вместе с моделями."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- User / auth ---


class UserOut(ORMModel):
    id: int
    email: str
    name: str
    role: str


class LoginIn(BaseModel):
    email: str
    password: str


class LoginOut(BaseModel):
    token: str
    user: UserOut


# --- Entity ---


class EntityIn(BaseModel):
    name: str
    type: str = "generic"
    status: str = "new"
    category: str | None = None
    city: str | None = None
    amount: float = 0.0
    description: str | None = None
    owner_id: int | None = None


class EntityOut(ORMModel):
    id: int
    name: str
    type: str
    status: str
    category: str | None
    city: str | None
    amount: float
    description: str | None
    owner_id: int | None
    created_at: datetime


# --- Event ---


class EventIn(BaseModel):
    entity_id: int | None = None
    user_id: int | None = None
    type: str
    status: str = "done"
    value: float = 0.0
    comment: str | None = None


class EventOut(ORMModel):
    id: int
    entity_id: int | None
    user_id: int | None
    type: str
    status: str
    value: float
    comment: str | None
    created_at: datetime


# --- Дашборд ---


class MetricCard(BaseModel):
    key: str
    label: str
    value: float
    unit: str = ""
    delta_pct: float | None = None  # изменение к прошлому периоду, %


class TimeseriesPoint(BaseModel):
    date: str  # YYYY-MM-DD
    count: int
    amount: float


class DashboardSummary(BaseModel):
    cards: list[MetricCard]
    timeseries: list[TimeseriesPoint]


# --- AI ---


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []  # [{"role": "user"|"assistant", "content": "..."}]


class AiCallOut(ORMModel):
    id: int
    created_at: datetime
    purpose: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    cost_usd: float
    cached: bool
    status: str


class AiMetricsSummary(BaseModel):
    total_calls: int
    ok_calls: int
    error_calls: int
    fallback_calls: int
    cached_calls: int
    cache_hit_rate: float
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    total_cost_usd: float
    avg_latency_ms: float
    p95_latency_ms: float
    by_purpose: list[dict]
    recent: list[AiCallOut]
