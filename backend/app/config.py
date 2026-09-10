"""Конфиг приложения. Всё читается из .env в корне репозитория."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # .env ищем сначала в корне монорепо, потом в backend/ — чтобы работало
        # и из корня (make dev), и из backend/ (uvicorn вручную).
        env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "HackAlem Starter"
    database_url: str = "sqlite:///./app.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    backend_port: int = 8000

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 30.0
    openai_max_retries: int = 3
    openai_max_output_tokens: int = 800

    ai_cache_enabled: bool = True
    ai_cache_ttl_seconds: int = 3600

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        """Относительный путь к sqlite якорим на backend/, чтобы seed и сервер
        всегда писали в один и тот же файл независимо от рабочей директории."""
        prefix = "sqlite:///./"
        if self.database_url.startswith(prefix):
            rel = self.database_url[len(prefix):]
            return f"sqlite:///{(BACKEND_DIR / rel).as_posix()}"
        return self.database_url

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
