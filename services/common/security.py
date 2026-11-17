"""Проверка JWT и прав. Общий код для всех сервисов: access-токен выпускает auth,
остальные сервисы проверяют подпись общим секретом и берут права из claims."""
import hmac
import os
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALG = "HS256"
# межсервисные вызовы (/internal/*): планировщик и бот ходят в сервисы напрямую, мимо gateway
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", "dev-service-token")


def require_service(x_service_token: str | None = Header(default=None)) -> None:
    if not x_service_token or not hmac.compare_digest(x_service_token, SERVICE_TOKEN):
        raise HTTPException(401, "Нужен сервисный токен")


@dataclass(frozen=True)
class Principal:
    user_id: int
    email: str
    role: str
    perms: frozenset[str]


def decode_token(token: str, expected_type: str) -> dict:
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG],
                            options={"require": ["exp", "sub", "type", "jti"]})
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Токен просрочен")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Неверный токен")
    if claims["type"] != expected_type:
        raise HTTPException(401, "Неверный тип токена")
    return claims


def current_principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Нужен заголовок Authorization: Bearer <token>",
                            headers={"WWW-Authenticate": "Bearer"})
    claims = decode_token(authorization[7:], "access")
    return Principal(int(claims["sub"]), claims["email"], claims["role"], frozenset(claims["perms"]))


def require(*perms: str):
    """Зависимость FastAPI: пускает только с нужными правами, иначе 403."""
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        missing = [p for p in perms if p not in principal.perms]
        if missing:
            raise HTTPException(403, f"Нет прав: {', '.join(missing)}")
        return principal
    return dependency
