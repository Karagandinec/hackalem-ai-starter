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


# --- Asset (единица техники) ---


class AssetIn(BaseModel):
    name: str
    type: str = "самосвал"
    status: str = "в работе"
    brand: str | None = None
    site: str | None = None
    output_tonnes: float = 0.0
    engine_hours: float = 0.0
    description: str | None = None
    owner_id: int | None = None


class AssetOut(ORMModel):
    id: int
    name: str
    type: str
    status: str
    brand: str | None
    site: str | None
    output_tonnes: float
    engine_hours: float
    description: str | None
    ai_label: str | None
    ai_score: float | None
    owner_id: int | None
    created_at: datetime


class ImportResult(BaseModel):
    """Итог загрузки файла: сколько строк приняли, сколько пропустили и почему."""

    imported: int
    skipped: int
    errors: list[str]
    columns_used: list[str]


# --- Event (событие с техникой) ---


class EventIn(BaseModel):
    asset_id: int | None = None
    user_id: int | None = None
    type: str
    status: str = "закрыто"
    downtime_hours: float = 0.0
    comment: str | None = None


class EventOut(ORMModel):
    id: int
    asset_id: int | None
    user_id: int | None
    type: str
    status: str
    downtime_hours: float
    comment: str | None
    created_at: datetime


# --- Дашборд ---


class MetricCard(BaseModel):
    key: str
    label: str
    value: float
    unit: str = ""
    delta_pct: float | None = None  # изменение к прошлому периоду, %
    # Для простоев и отказов рост — это плохо. Без этого признака фронт красит
    # падение простоев красным, а рост аварий зелёным.
    lower_is_better: bool = False


class TimeseriesPoint(BaseModel):
    date: str  # YYYY-MM-DD
    downtime_hours: float
    events: int


class DashboardSummary(BaseModel):
    cards: list[MetricCard]
    timeseries: list[TimeseriesPoint]


# --- AI ---


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []  # [{"role": "user"|"assistant", "content": "..."}]


class EnrichIn(BaseModel):
    """Какую технику разметить моделью и по какой инструкции."""

    asset_ids: list[int] = []  # пусто — возьмём последние limit единиц без разметки
    instruction: str = ""      # чем должна быть разметка; по умолчанию — риск отказа
    limit: int = 10


class EnrichedRow(BaseModel):
    id: int
    name: str
    ai_label: str | None
    ai_score: float | None
    reason: str = ""


class EnrichResult(BaseModel):
    processed: int
    status: str  # ok | fallback — заглушка, если модель недоступна
    cost_usd: float
    rows: list[EnrichedRow]


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
