"""Наполнение базы демо-данными.

    python scripts/seed.py                # пересоздать базу и залить 400 записей
    python scripts/seed.py --entities 300 # другое количество
    python scripts/seed.py --keep         # дописать, не удаляя существующее

По умолчанию база пересоздаётся: миграций в проекте нет, поменял модель — просто
прогони seed заново.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Чтобы `python scripts/seed.py` видел пакет app/ без установки проекта.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import hash_password  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Entity, Event, User  # noqa: E402
from scripts.generate_demo_data import build_dataset  # noqa: E402


def seed(entities: int = 400, days: int = 60, keep: bool = False) -> None:
    if not keep:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    data = build_dataset(entities=entities, days=days)
    db = SessionLocal()
    try:
        users = [
            User(
                email=u["email"],
                name=u["name"],
                role=u["role"],
                password_hash=hash_password(u["password"]),
            )
            for u in data["users"]
        ]
        db.add_all(users)
        db.flush()  # получаем id, они нужны как owner_id

        entity_objects = [
            Entity(
                name=row["name"],
                type=row["type"],
                status=row["status"],
                category=row["category"],
                city=row["city"],
                amount=row["amount"],
                description=row["description"],
                owner_id=users[row["owner_index"]].id,
                created_at=row["created_at"],
            )
            for row in data["entities"]
        ]
        db.add_all(entity_objects)
        db.flush()

        db.add_all(
            Event(
                entity_id=entity_objects[row["entity_index"]].id,
                user_id=users[row["user_index"]].id,
                type=row["type"],
                status=row["status"],
                value=row["value"],
                comment=row["comment"],
                created_at=row["created_at"],
            )
            for row in data["events"]
        )
        db.commit()
    finally:
        db.close()

    print(f"База:     {settings.sqlalchemy_url}")
    print(f"users:    {len(data['users'])}")
    print(f"entities: {len(data['entities'])}")
    print(f"events:   {len(data['events'])}")
    print("Логин для демо: demo@hackalem.kz / demo")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Залить демо-данные в базу")
    parser.add_argument("--entities", type=int, default=400, help="сколько сущностей создать (300-500)")
    parser.add_argument("--days", type=int, default=60, help="за сколько последних дней разбросать данные")
    parser.add_argument("--keep", action="store_true", help="не удалять существующие таблицы")
    args = parser.parse_args()
    seed(entities=args.entities, days=args.days, keep=args.keep)
