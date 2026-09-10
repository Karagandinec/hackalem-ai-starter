# HackAlem AI — стартовый каркас

Заготовка под хакатон **HackAlem AI** (23 сентября, Астана, 5 часов на разработку).
Кейс объявляют на месте, поэтому здесь нет предметной логики — только то, что на любом
хакатоне пишется первым и съедает первый час: запуск, база, авторизация, дашборд, чат
с моделью, логирование вызовов и демо-данные.

Ставится за несколько минут, дальше всё время уходит на кейс.

---

## Что уже готово

**Backend (FastAPI + SQLAlchemy + SQLite)**

- health-check, CORS, конфиг из `.env`
- три универсальные модели под переименование: `Entity`, `Event`, `User`
- CRUD, фильтры, эндпоинт дашборда (4 метрики + ряд для графика)
- демо-авторизация без JWT (логин, токен, `Authorization: Bearer`)
- seed-скрипт и генератор реалистичных демо-данных (400 записей, сезонность, воронка)

**Модуль `backend/app/ai/`**

- обёртка над OpenAI: ретраи, таймауты, лимит токенов, кэш ответов
- Structured Outputs — ответ строго по JSON Schema
- function calling с тремя инструментами: чтение из БД, запись в БД, агрегат
- **заглушка-фолбэк**: нет ключа или упал API — приложение продолжает работать
- таблица `ai_calls`: промпт, ответ, токены, латентность, стоимость каждого вызова
- эндпоинт сводки `/api/ai/metrics`

**Frontend (Vite + React + TypeScript)**

- тёмная тема, сайдбар, роутинг
- дашборд: 4 карточки-метрики, график, таблица с фильтром по датам
- чат с агентом со стримингом ответа (SSE) и показом вызванных инструментов
- страница AI-метрик

---

## Быстрый старт

Нужны Python 3.11+ и Node 18+.

```bash
git clone https://github.com/Karagandinec/hackalem-ai-starter.git
cd hackalem-ai-starter
```

**1. Ключи**

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Открой `.env` и вставь `OPENAI_API_KEY`. Без ключа проект тоже запустится — AI будет
отвечать заглушкой, всё остальное работает.

**2. Зависимости и данные**

```bash
make setup
make seed
```

Нет `make` (обычное дело на Windows) — рядом лежит шим с теми же командами:

```powershell
.\make.cmd setup
.\make.cmd seed
```

**3. Запуск**

```bash
make dev          # или .\make.cmd dev
```

- фронт — http://localhost:5173
- API и Swagger — http://localhost:8000/docs
- демо-логин — `demo@hackalem.kz` / `demo`

**4. Проверка перед коммитом**

```bash
make check        # pytest + tsc --noEmit, обе команды завершаются сами
```

---

## Структура

```
.
├── AGENTS.md              # правила для Codex — читай, если правишь код агентом
├── Makefile / make.cmd    # одни и те же команды для Unix и Windows
├── .env.example           # шаблон переменных; настоящий .env в .gitignore
├── backend/
│   ├── app/
│   │   ├── main.py        # точка входа FastAPI, CORS, подключение роутов
│   │   ├── config.py      # настройки из .env
│   │   ├── db.py          # движок, сессия, init_db
│   │   ├── models.py      # Entity, Event, User + ai_calls, ai_cache
│   │   ├── schemas.py     # pydantic-схемы запросов и ответов
│   │   ├── auth.py        # демо-авторизация без JWT
│   │   ├── routers/
│   │   │   ├── core.py    # health, логин, CRUD, дашборд
│   │   │   └── ai.py      # чат-стрим, structured outputs, метрики
│   │   └── ai/
│   │       ├── client.py  # обёртка над OpenAI: ретраи, кэш, лог, фолбэк
│   │       ├── tools.py   # три инструмента для function calling
│   │       ├── agent.py   # цикл «модель → инструменты → ответ стримом»
│   │       └── schemas.py # JSON Schema для Structured Outputs
│   ├── scripts/
│   │   ├── seed.py                # заливка базы
│   │   └── generate_demo_data.py  # генератор демо-данных
│   └── tests/test_smoke.py        # то, что гоняет make check
└── frontend/src/
    ├── api.ts             # все запросы к бэкенду + чтение SSE
    ├── components/        # Layout, MetricCard, Chart, DataTable
    ├── pages/             # Dashboard, Entities, Chat, AiMetrics
    └── styles.css         # тёмная тема, цвета переменными
```

---

## Как подогнать под кейс

Порядок действий, когда кейс объявили:

1. **Переименовать модели.** В `backend/app/models.py` `Entity` → то, чем является главный
   объект кейса (`Order`, `Patient`, `Route`, `Vacancy`), `Event` → что с ним происходит.
   Лишние поля удалить, недостающие добавить. Следом поправить `schemas.py`.
2. **Перегенерить данные.** Списки категорий, городов, статусов и сумм — в
   `backend/scripts/generate_demo_data.py`. Потом `make seed`.
3. **Поправить дашборд.** Четыре карточки и график считаются в одном месте — функция
   `dashboard()` в `backend/app/routers/core.py`.
4. **Настроить агента.** Промпт — `SYSTEM_PROMPT` в `backend/app/ai/agent.py`. Нужен свой
   инструмент — добавить в `backend/app/ai/tools.py` (описание + функция + `TOOL_HANDLERS`).
5. **Схема ответа модели.** Если нужен строгий JSON — добавить схему в
   `backend/app/ai/schemas.py` и вызвать `complete(..., json_schema=...)`.

Миграций нет намеренно: поменял модель — `make seed`, база пересоздалась.

---

## Полезные эндпоинты

| Метод | Путь                    | Что делает                                      |
| ----- | ----------------------- | ----------------------------------------------- |
| GET   | `/api/health`           | жив ли сервер, видит ли базу, есть ли ключ AI    |
| POST  | `/api/auth/login`       | демо-логин, возвращает токен                     |
| GET   | `/api/entities`         | список с фильтрами по датам, статусу, поиску     |
| GET   | `/api/dashboard?days=30`| 4 карточки + ряд для графика                     |
| POST  | `/api/ai/chat`          | чат с агентом, поток SSE                         |
| POST  | `/api/ai/insights`      | Structured Outputs: выводы по данным             |
| POST  | `/api/ai/classify`      | Structured Outputs: классификация текста         |
| GET   | `/api/ai/metrics`       | сводка вызовов: токены, деньги, латентность      |
| GET   | `/api/ai/calls/{id}`    | полный промпт и ответ одного вызова              |

Полный список — в Swagger на http://localhost:8000/docs.

---

## Работа с Codex

В корне лежит [AGENTS.md](AGENTS.md) — Codex подхватывает его автоматически. Там стек,
команды, стиль и жёсткое правило: **`npm run dev` и `uvicorn` нельзя запускать как
команду проверки** — они не завершаются и вешают агента до таймаута. Проверка — `make check`.

Если правишь код руками, а не агентом, AGENTS.md всё равно полезен: это короткая памятка
по проекту.

---

## Если что-то не работает

| Симптом                                   | Что делать                                                      |
| ----------------------------------------- | --------------------------------------------------------------- |
| В сайдбаре «backend недоступен»           | Не поднят backend. `make dev`, проверь http://localhost:8000/docs |
| «⚠ AI в режиме заглушки»                  | Нет `OPENAI_API_KEY` в `.env`. Вставь ключ и перезапусти backend  |
| Дашборд пустой                            | Не залиты данные: `make seed`                                    |
| `make: command not found`                 | Используй `.\make.cmd <команда>`                                 |
| 404 на модель / ошибка от OpenAI          | Поменяй `OPENAI_MODEL` в `.env` на доступную модель              |
| Кракозябры в консоли Windows              | Команды из Makefile уже ставят `PYTHONUTF8=1`; вручную — тоже    |
| Порт 8000 занят                           | `make dev BACKEND_PORT=8010` и поправь `VITE_API_URL` в `.env`   |

---

Лицензия — MIT, бери и переделывай.
