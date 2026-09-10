"""Точка входа FastAPI.

Запуск:  uvicorn app.main:app --reload --port 8000   (из папки backend)
Доки:    http://localhost:8000/docs

В деплое (Docker) этот же процесс отдаёт и собранный фронт из frontend/dist,
поэтому проверяющему хватает одной ссылки: / — приложение, /docs — API.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import ROOT_DIR, settings
from app.db import init_db
from app.routers import ai as ai_router
from app.routers import core as core_router

# Собранный фронт. В деве его нет (там Vite на :5173) — тогда / ведёт в /docs.
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"


def seed_if_empty() -> None:
    """На бесплатном хостинге диск чистится при каждом рестарте, и проверяющий
    открыл бы пустой дашборд. Поэтому в контейнере база наливается сама —
    но только если она пуста, чтобы не затирать введённое во время демо."""
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Asset

    db = SessionLocal()
    try:
        if db.scalar(select(func.count(Asset.id))):
            return
    finally:
        db.close()

    from scripts.seed import seed

    seed(keep=True)  # таблицы уже созданы init_db, дропать нечего


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # таблицы создаются при старте, миграций нет — так быстрее на хакатоне
    if settings.seed_on_start:
        seed_if_empty()
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


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        """Отдаём файл, если он есть, иначе index.html: у React Router свои
        адреса (/fleet, /chat), и по F5 сервер обязан вернуть то же приложение.
        Роуты /api и /docs зарегистрированы выше и сюда не попадают."""
        # Несуществующий эндпоинт должен быть 404, а не молча index.html:
        # иначе фронт получит HTML вместо JSON и упадёт с невнятной ошибкой.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail=f"Нет такого эндпоинта: /{full_path}")
        dist = FRONTEND_DIST.resolve()
        candidate = (dist / full_path).resolve()
        # full_path приходит от клиента: не выпускаем его за пределы dist.
        if full_path and candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
        index = dist / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="Фронт не собран: нет frontend/dist/index.html")
        return FileResponse(index)

else:

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/docs")
