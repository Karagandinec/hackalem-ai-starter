"""Роуты AI: чат со стримингом, structured outputs, метрики вызовов."""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.agent import run_agent_stream
from app.ai.client import complete
from app.ai.schemas import CLASSIFY_SCHEMA, INSIGHT_SCHEMA
from app.db import SessionLocal, get_db
from app.models import AiCall
from app.schemas import AiCallOut, AiMetricsSummary, ChatIn

router = APIRouter(prefix="/ai", tags=["ai"])


# --- Чат со стримингом ------------------------------------------------------


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@router.post("/chat")
def chat(payload: ChatIn) -> StreamingResponse:
    """Server-Sent Events. Фронт читает поток и печатает ответ по мере поступления.

    Сессию БД открываем внутри генератора и закрываем в finally: обычная
    зависимость get_db может закрыться раньше, чем поток досочится.
    """

    def event_stream() -> Iterator[str]:
        db: Session = SessionLocal()
        try:
            for event in run_agent_stream(db, payload.message, payload.history):
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001 — поток не должен обрываться молча
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            db.close()
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# --- Structured outputs -----------------------------------------------------


@router.post("/insights")
def insights(db: Session = Depends(get_db), context: str = Body("", embed=True)) -> dict:
    """Пример Structured Outputs: модель возвращает JSON строго по INSIGHT_SCHEMA.

    context — любой текст или выгрузка цифр, по которым нужно сделать выводы.
    """
    from app.ai.tools import tool_aggregate_metrics

    facts = {
        "по статусам": tool_aggregate_metrics(db, table="entities", metric="count", group_by="status"),
        "сумма по дням": tool_aggregate_metrics(db, table="entities", metric="sum", group_by="day"),
        "средний чек": tool_aggregate_metrics(db, table="entities", metric="avg", group_by="none"),
    }
    result = complete(
        db,
        [
            {"role": "system", "content": "Ты аналитик. Отвечай по-русски, опирайся только на цифры из данных."},
            {
                "role": "user",
                "content": f"Данные:\n{json.dumps(facts, ensure_ascii=False, default=str)}\n\nЗадача: {context or 'дай выводы по данным'}",
            },
        ],
        purpose="insights",
        json_schema=INSIGHT_SCHEMA,
        schema_name="insights",
    )
    return {"status": result.status, "data": result.data, "cost_usd": result.cost_usd, "error": result.error}


@router.post("/classify")
def classify(db: Session = Depends(get_db), text: str = Body(..., embed=True)) -> dict:
    """Пример Structured Outputs №2: разложить произвольный текст по полям."""
    result = complete(
        db,
        [
            {"role": "system", "content": "Классифицируй обращение. Отвечай по-русски."},
            {"role": "user", "content": text},
        ],
        purpose="classify",
        json_schema=CLASSIFY_SCHEMA,
        schema_name="classification",
    )
    return {"status": result.status, "data": result.data, "cost_usd": result.cost_usd, "error": result.error}


# --- Метрики вызовов --------------------------------------------------------


@router.get("/metrics", response_model=AiMetricsSummary)
def ai_metrics(db: Session = Depends(get_db), limit: int = Query(20, le=200)) -> AiMetricsSummary:
    """Сводка по таблице ai_calls: сколько вызовов, токенов, денег, как быстро."""
    totals = db.execute(
        select(
            func.count(AiCall.id),
            func.coalesce(func.sum(AiCall.total_tokens), 0),
            func.coalesce(func.sum(AiCall.prompt_tokens), 0),
            func.coalesce(func.sum(AiCall.completion_tokens), 0),
            func.coalesce(func.sum(AiCall.cost_usd), 0.0),
            func.coalesce(func.avg(AiCall.latency_ms), 0.0),
        )
    ).one()
    total_calls, total_tokens, prompt_tokens, completion_tokens, total_cost, avg_latency = totals

    def count_where(condition) -> int:
        return db.scalar(select(func.count(AiCall.id)).where(condition)) or 0

    cached_calls = count_where(AiCall.cached.is_(True))
    latencies = sorted(db.scalars(select(AiCall.latency_ms)).all())
    p95 = float(latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)]) if latencies else 0.0

    by_purpose = [
        {
            "purpose": purpose,
            "calls": calls,
            "tokens": int(tokens or 0),
            "cost_usd": round(float(cost or 0), 6),
            "avg_latency_ms": round(float(latency or 0)),
        }
        for purpose, calls, tokens, cost, latency in db.execute(
            select(
                AiCall.purpose,
                func.count(AiCall.id),
                func.sum(AiCall.total_tokens),
                func.sum(AiCall.cost_usd),
                func.avg(AiCall.latency_ms),
            )
            .group_by(AiCall.purpose)
            .order_by(func.count(AiCall.id).desc())
        ).all()
    ]

    recent = db.scalars(select(AiCall).order_by(AiCall.created_at.desc()).limit(limit)).all()

    return AiMetricsSummary(
        total_calls=total_calls,
        ok_calls=count_where(AiCall.status.in_(("ok", "cached"))),
        error_calls=count_where(AiCall.status == "error"),
        fallback_calls=count_where(AiCall.status == "fallback"),
        cached_calls=cached_calls,
        cache_hit_rate=round(cached_calls / total_calls * 100, 1) if total_calls else 0.0,
        total_tokens=int(total_tokens),
        prompt_tokens=int(prompt_tokens),
        completion_tokens=int(completion_tokens),
        total_cost_usd=round(float(total_cost), 6),
        avg_latency_ms=round(float(avg_latency)),
        p95_latency_ms=p95,
        by_purpose=by_purpose,
        recent=[AiCallOut.model_validate(row) for row in recent],
    )


@router.get("/calls/{call_id}")
def ai_call_detail(call_id: int, db: Session = Depends(get_db)) -> dict:
    """Полный промпт и ответ одного вызова — чтобы отлаживать промпты глазами."""
    row = db.get(AiCall, call_id)
    if row is None:
        return {"error": "не найдено"}
    return {
        "id": row.id,
        "created_at": row.created_at,
        "purpose": row.purpose,
        "model": row.model,
        "prompt": row.prompt,
        "response": row.response,
        "tool_calls": json.loads(row.tool_calls) if row.tool_calls else [],
        "total_tokens": row.total_tokens,
        "latency_ms": row.latency_ms,
        "cost_usd": row.cost_usd,
        "status": row.status,
        "error": row.error,
    }
