"""Генератор демо-данных: парк техники на угольном разрезе и события с ней.

Не просто рандом. Заложены зависимости, которые видно на дашборде и за которые
модели есть чем зацепиться:
  * чем больше наработка (моточасы), тем чаще отказы — основа для предиктивки;
  * разрез работает круглосуточно, поэтому недельной «ямы» нет, но есть
    несколько тяжёлых дней с крупными простоями (авария, метель);
  * выработка зависит от типа техники: возит самосвал, а буровой станок не возит;
  * техника не «в работе» тонны в эту смену не выдаёт.

Отдельно от seed.py, чтобы данные можно было генерировать и в тестах:
    from scripts.generate_demo_data import build_dataset
    data = build_dataset(assets=140)

Запуск как скрипта печатает сводку, ничего не записывая:
    python scripts/generate_demo_data.py
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

RANDOM_SEED = 42  # фиксируем, чтобы демо было одинаковым на всех ноутбуках команды

# (тип, марки, доля парка, тонн за смену, множитель риска отказа)
FLEET = [
    ("самосвал", ("БелАЗ-75306", "БелАЗ-7555", "Caterpillar 777"), 0.40, 900, 1.0),
    ("экскаватор", ("Komatsu PC1250", "Hitachi EX1200", "ЭКГ-10"), 0.18, 0, 1.3),
    ("буровой станок", ("Sandvik DR412i", "Atlas Copco PV-271", "СБШ-250МНА"), 0.12, 0, 1.2),
    ("бульдозер", ("Komatsu D375A", "Caterpillar D9R", "Т-35.01"), 0.14, 0, 0.9),
    ("конвейер", ("КЛМ-1200", "ЛКЛ-1000"), 0.08, 0, 0.7),
    ("насосная установка", ("ЦНС-300", "ГрТ-1600"), 0.08, 0, 0.6),
]

SITES = [
    ("Разрез «Восточный»", 0.34),
    ("Разрез «Северный»", 0.26),
    ("Карьер «Жайрем»", 0.18),
    ("Шахта «Центральная»", 0.14),
    ("Обогатительная фабрика", 0.08),
]

STATUSES = [("в работе", 0.62), ("ТО", 0.12), ("в ремонте", 0.14), ("простой", 0.07), ("резерв", 0.05)]

# (тип события, доля, диапазон часов простоя)
EVENT_TYPES = [
    ("отказ", 0.26, (4, 36)),
    ("внеплановый ремонт", 0.20, (6, 48)),
    ("плановое ТО", 0.24, (3, 12)),
    ("простой по погоде", 0.12, (2, 14)),
    ("простой по организации", 0.10, (1, 6)),
    ("нарушение ТБ", 0.05, (0, 2)),
    ("авария", 0.03, (24, 96)),
]

FAILURE_REASONS = [
    "течь гидравлики стрелы",
    "пробой шины заднего моста",
    "перегрев ДВС, сработала защита",
    "износ футеровки кузова",
    "обрыв троса подъёмного механизма",
    "выход из строя топливного насоса",
    "трещина в раме, требуется сварка",
    "отказ пневмосистемы тормозов",
    "износ бурового става",
    "заклинил редуктор поворота",
]
ROUTINE_REASONS = [
    "ТО-2 по регламенту, 250 моточасов",
    "замена масла и фильтров",
    "плановая диагностика ходовой",
    "нет самосвалов под погрузку",
    "метель, работы на уступе остановлены",
    "ожидание автотопливозаправщика",
    "смена экипажа задержана",
    "проверка средств защиты на участке",
]


def _weighted(items: list[tuple], rnd: random.Random):
    return rnd.choices([i[0] for i in items], weights=[i[1] for i in items], k=1)[0]


def _created_at(rnd: random.Random, days: int, now: datetime) -> datetime:
    """Равномерно по суткам: разрез работает в три смены, ночного провала почти нет."""
    day_offset = rnd.randrange(days)
    candidate = (now - timedelta(days=day_offset)).replace(
        hour=rnd.randrange(24), minute=rnd.randrange(60), second=rnd.randrange(60), microsecond=0
    )
    return min(candidate, now)


def build_dataset(assets: int = 140, days: int = 60, seed: int = RANDOM_SEED) -> dict:
    """Возвращает {"users": [...], "assets": [...], "events": [...]} — обычные dict,
    чтобы seed.py просто раскидал их по моделям."""
    rnd = random.Random(seed)
    # Наивный UTC — как и во всех моделях (app/models.utcnow). Локальное время
    # дало бы записи «из будущего» относительно фильтров дашборда.
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    users = [
        {"email": "demo@hackalem.kz", "name": "Демо Диспетчер", "role": "диспетчер", "password": "demo"},
        {"email": "master@hackalem.kz", "name": "Ерлан Сериков", "role": "мастер", "password": "master"},
        {"email": "mechanic@hackalem.kz", "name": "Виктор Кузнецов", "role": "механик", "password": "mechanic"},
    ]

    # Пара тяжёлых дней: крупная авария и метель. На графике простоев видны пики,
    # а агенту есть что найти в ответ на «что случилось на прошлой неделе».
    bad_days = {rnd.randrange(3, days // 2), rnd.randrange(days // 2, days - 2)}

    fleet_shares = [(item[0], item[2]) for item in FLEET]
    spec = {item[0]: item for item in FLEET}

    asset_rows: list[dict] = []
    event_rows: list[dict] = []

    for index in range(assets):
        asset_type = _weighted(fleet_shares, rnd)
        _, brands, _, tonnes_per_shift, risk_factor = spec[asset_type]
        brand_full = rnd.choice(brands)
        status = _weighted(STATUSES, rnd)
        engine_hours = round(rnd.triangular(500, 32000, 9000))

        # Выработка: только то, что реально возит, и только если техника на ходу.
        output = 0.0
        if tonnes_per_shift and status == "в работе":
            output = max(0.0, float(round(rnd.gauss(tonnes_per_shift, tonnes_per_shift * 0.18) / 10) * 10))

        asset_rows.append(
            {
                "index": index,
                "name": f"{brand_full} №{100 + index}",
                "type": asset_type,
                "status": status,
                "brand": brand_full.split()[0],
                "site": _weighted(SITES, rnd),
                "output_tonnes": output,
                "engine_hours": float(engine_hours),
                "description": f"{asset_type}, наработка {engine_hours} мч",
                "owner_index": rnd.randrange(len(users)),
                "created_at": now - timedelta(days=rnd.randrange(days, days * 6)),  # в парке давно
            }
        )

        # Чем выше наработка и «капризнее» тип, тем больше событий у единицы.
        wear = engine_hours / 32000
        expected = 1 + wear * 6 * risk_factor
        for _ in range(max(0, int(rnd.gauss(expected, 1.2)))):
            event_type = _weighted([(e[0], e[1]) for e in EVENT_TYPES], rnd)
            low, high = next(e[2] for e in EVENT_TYPES if e[0] == event_type)
            created = _created_at(rnd, days, now)
            hours = round(rnd.uniform(low, high), 1)
            if (now - created).days in bad_days:
                hours = round(hours * rnd.uniform(1.8, 3.0), 1)  # тяжёлый день
            breakdown = event_type in ("отказ", "внеплановый ремонт", "авария")
            event_rows.append(
                {
                    "asset_index": index,
                    "user_index": rnd.randrange(len(users)),
                    "type": event_type,
                    "status": rnd.choices(["закрыто", "в работе"], weights=[0.85, 0.15])[0],
                    "downtime_hours": hours,
                    "comment": rnd.choice(FAILURE_REASONS if breakdown else ROUTINE_REASONS),
                    "created_at": created,
                }
            )

    return {"users": users, "assets": asset_rows, "events": event_rows}


if __name__ == "__main__":
    data = build_dataset()
    downtime = sum(e["downtime_hours"] for e in data["events"])
    output = sum(a["output_tonnes"] for a in data["assets"])
    print(f"users:      {len(data['users'])}")
    print(f"техника:    {len(data['assets'])}")
    print(f"события:    {len(data['events'])}")
    print(f"простои:    {downtime:,.0f} ч".replace(",", " "))
    print(f"выработка:  {output:,.0f} т за смену".replace(",", " "))
    print("Ничего не записано — это только предпросмотр. Запись в базу: python scripts/seed.py")
