# HackAlem AI — стартовый каркас.
#
#   make setup   — поставить зависимости (один раз)
#   make seed    — залить демо-данные в SQLite
#   make dev     — поднять backend (:8000) и frontend (:5173)
#   make check   — тесты бэкенда + проверка типов фронта (быстро, само завершается)
#   make clean   — снести venv, node_modules, базу
#
# Если make не установлен (обычная ситуация на Windows) — рядом лежит make.cmd
# с теми же командами: в PowerShell пиши `.\make.cmd dev`.

export PYTHONUTF8 := 1

ifeq ($(OS),Windows_NT)
  VENV_PY := .venv/Scripts/python.exe
  SYS_PY  := python
else
  VENV_PY := .venv/bin/python
  SYS_PY  := python3
endif

BACKEND_PORT ?= 8000

.PHONY: help setup setup-backend setup-frontend dev dev-backend dev-frontend seed check check-backend check-frontend build clean

help:
	@echo "make setup  - поставить зависимости"
	@echo "make seed   - залить демо-данные (400 записей)"
	@echo "make dev    - backend :$(BACKEND_PORT) + frontend :5173"
	@echo "make check  - тесты и типы"
	@echo "make clean  - удалить venv, node_modules, app.db"

# --- Установка --------------------------------------------------------------

setup: setup-backend setup-frontend
	@echo ""
	@echo "Готово. Скопируй .env.example в .env, вставь OPENAI_API_KEY, потом: make seed && make dev"

setup-backend:
	cd backend && $(SYS_PY) -m venv .venv
	cd backend && $(VENV_PY) -m pip install --upgrade pip
	cd backend && $(VENV_PY) -m pip install -r requirements.txt

setup-frontend:
	cd frontend && npm install

# --- Разработка -------------------------------------------------------------

# Оба сервера параллельно. Ctrl+C гасит оба.
dev:
	@echo "backend  -> http://localhost:$(BACKEND_PORT)/docs"
	@echo "frontend -> http://localhost:5173"
	@$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && $(VENV_PY) -m uvicorn app.main:app --reload --port $(BACKEND_PORT)

dev-frontend:
	cd frontend && npm run dev

seed:
	cd backend && $(VENV_PY) scripts/seed.py

# --- Проверки ---------------------------------------------------------------
# ВАЖНО: тут только команды, которые завершаются сами. Никаких серверов.

check: check-backend check-frontend
	@echo "check пройден"

check-backend:
	cd backend && $(VENV_PY) -m pytest

check-frontend:
	cd frontend && npm run typecheck

build:
	cd frontend && npm run build

# --- Уборка -----------------------------------------------------------------

clean:
	rm -rf backend/.venv backend/app.db backend/.pytest_cache frontend/node_modules frontend/dist
	@echo "Убрано. Дальше: make setup"
