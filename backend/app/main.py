"""Точка входа FastAPI.

Запуск:  uvicorn app.main:app --reload --port 8000   (из папки backend)
Доки:    http://localhost:8000/docs
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.config import settings
from app.db import init_db
from app.routers import ai as ai_router
from app.routers import core as core_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # таблицы создаются при старте, миграций нет — так быстрее на хакатоне
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(core_router.router, prefix="/api")
app.include_router(ai_router.router, prefix="/api")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")
