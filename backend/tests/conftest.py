"""Общая настройка тестов: отдельная временная база, AI выключен.

Переменные окружения ставим ДО импорта app — иначе конфиг успеет прочитать
настоящий .env и тесты пойдут в рабочую базу или в платный API.
"""

import os
import tempfile
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "hackalem_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["OPENAI_API_KEY"] = ""  # тесты не должны ходить в сеть и тратить деньги
os.environ["AI_CACHE_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
