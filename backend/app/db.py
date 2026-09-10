"""SQLAlchemy: движок, сессия, базовый класс моделей."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.sqlalchemy_url,
    # check_same_thread нужен только для sqlite: FastAPI ходит из разных потоков.
    connect_args={"check_same_thread": False} if settings.sqlalchemy_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """Зависимость FastAPI: сессия на один запрос."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Создаёт таблицы. Миграций нет намеренно: на хакатоне схему проще
    менять руками и пересоздавать базу (make seed)."""
    from app import models  # noqa: F401  — регистрирует модели в метаданных

    Base.metadata.create_all(bind=engine)
