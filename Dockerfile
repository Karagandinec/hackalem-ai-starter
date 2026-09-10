# Один контейнер на весь проект: FastAPI отдаёт и API, и собранный фронт.
# Проверяющему хватает одной ссылки, CORS и второй хостинг не нужны.
#
#   docker build -t hackalem .
#   docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... hackalem
#   -> http://localhost:8000

# --- шаг 1: собираем фронт ---------------------------------------------------
FROM node:22-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- шаг 2: рантайм ----------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    SEED_ON_START=true \
    PORT=8000

WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
# Тот же относительный путь, что и в репозитории: app/main.py ищет ../frontend/dist
COPY --from=frontend /build/dist /app/frontend/dist

EXPOSE 8000

# PORT задаёт хостинг (Render, Railway, Fly) — читаем его, а не хардкодим.
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
