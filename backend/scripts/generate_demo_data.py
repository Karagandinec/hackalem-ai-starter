"""Генератор реалистичных демо-данных.

Не просто рандом: есть недельная сезонность (в выходные меньше), тренд роста
к текущей дате, воронка статусов, суммы зависят от категории, у части записей
есть события. На графике это выглядит как настоящие данные, а не как шум.

Отдельно от seed.py, чтобы данные можно было генерировать и в тестах:
    from scripts.generate_demo_data import build_dataset
    data = build_dataset(entities=400)

Запуск как скрипта печатает сводку, ничего не записывая:
    python scripts/generate_demo_data.py
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

RANDOM_SEED = 42  # фиксируем, чтобы демо было одинаковым на всех ноутбуках команды

FIRST_NAMES = [
    "Айгерим", "Данияр", "Мадина", "Ерлан", "Алия", "Тимур", "Асель", "Нурлан",
    "Камила", "Арман", "Дана", "Санжар", "Жанна", "Бекзат", "Айсулу", "Руслан",
    "Динара", "Олжас", "Сабина", "Максим", "Ольга", "Игорь", "Елена", "Виталий",
]
LAST_NAMES = [
    "Сатпаев", "Абдрахманов", "Ким", "Нурланов", "Есенов", "Бекова", "Жумабаев",
    "Оспанов", "Ахметова", "Тулегенов", "Сериков", "Иванов", "Петрова", "Мусин",
    "Куанышев", "Тлеуберди", "Смагулов", "Байжанов", "Дюсенов", "Каримова",
]
CITIES = [
    ("Астана", 0.34), ("Алматы", 0.30), ("Шымкент", 0.11), ("Караганда", 0.09),
    ("Актобе", 0.06), ("Атырау", 0.05), ("Павлодар", 0.03), ("Костанай", 0.02),
]
CATEGORIES = [
    # (категория, доля, средний чек, разброс)
    ("Консультация", 0.30, 15_000, 6_000),
    ("Подписка", 0.25, 45_000, 15_000),
    ("Доставка", 0.20, 8_000, 3_500),
    ("Оборудование", 0.15, 180_000, 70_000),
    ("Обучение", 0.10, 65_000, 25_000),
]
TYPES = ["заявка", "заказ", "обращение", "сделка"]
STATUSES = [("new", 0.22), ("in_progress", 0.28), ("done", 0.40), ("cancelled", 0.10)]
SOURCES = ["instagram", "google", "2gis", "сарафан", "сайт", "whatsapp"]
EVENT_TYPES = ["звонок", "сообщение", "визит", "оплата", "смена статуса", "жалоба"]
COMMENTS = [
    "Клиент перезвонит сам",
    "Уточнили адрес доставки",
    "Просит счёт на юрлицо",
    "Оплата прошла картой",
    "Перенесли на следующую неделю",
    "Не отвечает второй день",
    "Оставил положительный отзыв",
    "Нужна доработка по срокам",
]


CATEGORIES_WEIGHTED = [(name, weight) for name, weight, _avg, _spread in CATEGORIES]
CATEGORY_PRICE = {name: (avg, spread) for name, _weight, avg, spread in CATEGORIES}


def _weighted(items: list[tuple], rnd: random.Random):
    values = [i[0] for i in items]
    weights = [i[1] for i in items]
    return rnd.choices(values, weights=weights, k=1)[0]


def _person(rnd: random.Random) -> str:
    return f"{rnd.choice(FIRST_NAMES)} {rnd.choice(LAST_NAMES)}"


def _created_at(rnd: random.Random, days: int, now: datetime) -> datetime:
    """Дата с недельной сезонностью и ростом к сегодняшнему дню."""
    for _ in range(30):
        # mode=0 => чем ближе к сегодня, тем плотнее записи: на графике виден рост.
        # Диапазон берём шире окна и лишнее отбрасываем — так рост плавный
        # (около +50% к прошлому месяцу), а не вертикальная стена.
        day_offset = int(rnd.triangular(0, days * 1.6, 0))
        if day_offset >= days:
            continue
        day = now - timedelta(days=day_offset)
        if day.weekday() >= 5 and rnd.random() > 0.45:
            continue  # в выходные активность ниже
        candidate = day.replace(
            hour=rnd.choices(range(8, 22), weights=[1, 2, 4, 6, 7, 7, 6, 6, 7, 8, 6, 4, 3, 2])[0],
            minute=rnd.randrange(60),
            second=rnd.randrange(60),
            microsecond=0,
        )
        if candidate <= now:  # записей из будущего быть не должно
            return candidate
    return now - timedelta(hours=rnd.randrange(1, 24))


def build_dataset(entities: int = 400, days: int = 60, seed: int = RANDOM_SEED) -> dict:
    """Возвращает {"users": [...], "entities": [...], "events": [...]} — обычные dict,
    чтобы seed.py просто раскидал их по моделям."""
    rnd = random.Random(seed)
    # Наивный UTC — как и во всех моделях (app/models.utcnow). Локальное время
    # дало бы записи «из будущего» относительно фильтров дашборда.
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    users = [
        {"email": "demo@hackalem.kz", "name": "Демо Пользователь", "role": "admin", "password": "demo"},
        {"email": "manager@hackalem.kz", "name": "Асель Бекова", "role": "manager", "password": "manager"},
        {"email": "operator@hackalem.kz", "name": "Данияр Ким", "role": "user", "password": "operator"},
    ]

    entity_rows: list[dict] = []
    event_rows: list[dict] = []

    for index in range(entities):
        category = _weighted(CATEGORIES_WEIGHTED, rnd)
        avg, spread = CATEGORY_PRICE[category]
        created = _created_at(rnd, days, now)
        status = _weighted(STATUSES, rnd)
        # Свежие записи чаще ещё в работе, старые — уже закрыты. Так воронка выглядит живой.
        if (now - created).days < 3 and status == "done" and rnd.random() < 0.6:
            status = rnd.choice(["new", "in_progress"])

        amount = max(1000, round(rnd.gauss(avg, spread) / 500) * 500)
        if status == "cancelled":
            amount = 0.0  # отменённые не приносят денег

        entity_rows.append(
            {
                "index": index,
                "name": _person(rnd),
                "type": rnd.choice(TYPES),
                "status": status,
                "category": category,
                "city": _weighted(CITIES, rnd),
                "amount": float(amount),
                "description": f"{category.lower()} · источник: {rnd.choice(SOURCES)}",
                "owner_index": rnd.randrange(len(users)),
                "created_at": created,
            }
        )

        # 0-3 события на запись, чем «дальше» статус, тем больше активности
        event_count = {"new": 0, "in_progress": 2, "done": 3, "cancelled": 1}[status]
        event_count = max(0, event_count + rnd.choice([-1, 0, 0, 1]))
        for step in range(event_count):
            offset_hours = rnd.randrange(1, max(2, (now - created).days * 24 or 2))
            event_rows.append(
                {
                    "entity_index": index,
                    "user_index": rnd.randrange(len(users)),
                    "type": rnd.choice(EVENT_TYPES),
                    "status": "done" if step < event_count - 1 else rnd.choice(["done", "pending"]),
                    "value": float(rnd.randrange(0, 5000, 250)),
                    "comment": rnd.choice(COMMENTS),
                    "created_at": min(now, created + timedelta(hours=offset_hours)),
                }
            )

    return {"users": users, "entities": entity_rows, "events": event_rows}



if __name__ == "__main__":
    data = build_dataset()
    total_amount = sum(e["amount"] for e in data["entities"])
    print(f"users:    {len(data['users'])}")
    print(f"entities: {len(data['entities'])}")
    print(f"events:   {len(data['events'])}")
    print(f"сумма:    {total_amount:,.0f} ₸".replace(",", " "))
    print("Ничего не записано — это только предпросмотр. Запись в базу: python scripts/seed.py")
