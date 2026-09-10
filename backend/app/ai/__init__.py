"""Модуль работы с OpenAI: клиент, инструменты, агент, JSON-схемы."""

from app.ai.agent import run_agent_stream
from app.ai.client import LlmResult, complete, estimate_cost, log_call, stream_text
from app.ai.schemas import CLASSIFY_SCHEMA, INSIGHT_SCHEMA
from app.ai.tools import TOOL_DEFINITIONS, run_tool

__all__ = [
    "CLASSIFY_SCHEMA",
    "INSIGHT_SCHEMA",
    "TOOL_DEFINITIONS",
    "LlmResult",
    "complete",
    "estimate_cost",
    "log_call",
    "run_agent_stream",
    "run_tool",
    "stream_text",
]
