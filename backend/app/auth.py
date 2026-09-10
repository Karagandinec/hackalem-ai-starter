"""Демо-авторизация без JWT.

Токен = "demo.<user_id>.<8 символов от sha256 email+соль>". Этого достаточно,
чтобы залогиниться на демо и показать роли, но это НЕ безопасно: подписи нет,
срок жизни не ограничен. Перед любым реальным использованием — заменить на JWT.
"""

import hashlib

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User

DEMO_SALT = "hackalem-demo"


def hash_password(password: str) -> str:
    return hashlib.sha256(f"{DEMO_SALT}:{password}".encode()).hexdigest()


def make_token(user: User) -> str:
    sig = hashlib.sha256(f"{DEMO_SALT}:{user.id}:{user.email}".encode()).hexdigest()[:8]
    return f"demo.{user.id}.{sig}"


def parse_token(token: str) -> int | None:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "demo" or not parts[1].isdigit():
        return None
    return int(parts[1])


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Обязательная авторизация: 401, если токена нет или он битый."""
    user = get_optional_user(authorization, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен заголовок Authorization: Bearer <token>")
    return user


def get_optional_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    """Мягкая авторизация: без токена вернёт None, роут работает как публичный."""
    if not authorization:
        return None
    token = authorization.removeprefix("Bearer ").strip()
    user_id = parse_token(token)
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None or make_token(user) != token:
        return None
    return user
