"""Сервис auth: регистрация, вход, JWT (access + refresh с ротацией), роли и права, журнал входов."""
import hashlib
import hmac
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import config, schemas
from auth.catalog import DEFAULT_ROLE, PERMISSIONS, ROLES
from auth.db import Base, SessionLocal, engine, get_db
from auth.events import outbox
from auth.models import LoginEvent, PasswordReset, Permission, RefreshToken, Role, RolePermission, User, utcnow
from common.security import (JWT_ALG, JWT_SECRET, Principal, current_principal, decode_token, require,
                             require_service)

PBKDF2_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    _, iterations, salt, digest = stored.split("$")
    calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    return hmac.compare_digest(calc.hex(), digest)


# для несуществующего email всё равно считаем хеш: время ответа не выдаёт, есть ли такой пользователь
_DUMMY_HASH = hash_password("dummy-password-1")


def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS auth"))
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for code, title in PERMISSIONS.items():
            if not db.get(Permission, code):
                db.add(Permission(code=code, title=title))
        for name, (title, _) in ROLES.items():
            if not db.get(Role, name):
                db.add(Role(name=name, title=title))
        db.flush()
        existing = set(db.execute(select(RolePermission.role, RolePermission.permission)).tuples())
        for name, (_, perms) in ROLES.items():
            for perm in perms:
                if (name, perm) not in existing:
                    db.add(RolePermission(role=name, permission=perm))
        if not db.scalar(select(User).where(User.email == config.ADMIN_EMAIL)):
            db.add(User(email=config.ADMIN_EMAIL, full_name="Администратор",
                        password_hash=hash_password(config.ADMIN_PASSWORD), role="admin"))
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    outbox.start_relay()
    yield


app = FastAPI(title="OfficeSpace · auth", root_path=config.ROOT_PATH, lifespan=lifespan)


def role_permissions(db: Session, role: str) -> list[str]:
    return sorted(db.scalars(select(RolePermission.permission).where(RolePermission.role == role)))


def issue_tokens(db: Session, user: User, family_id: str | None = None) -> schemas.TokenPair:
    now = utcnow()
    family_id = family_id or secrets.token_hex(16)
    refresh_jti = secrets.token_hex(16)
    access = jwt.encode({
        "sub": str(user.id), "email": user.email, "role": user.role,
        "perms": role_permissions(db, user.role), "type": "access", "jti": secrets.token_hex(8),
        "iat": now, "exp": now + timedelta(seconds=config.ACCESS_TTL_SECONDS),
    }, JWT_SECRET, JWT_ALG)
    refresh_exp = now + timedelta(seconds=config.REFRESH_TTL_SECONDS)
    refresh = jwt.encode({
        "sub": str(user.id), "type": "refresh", "jti": refresh_jti, "fam": family_id,
        "iat": now, "exp": refresh_exp,
    }, JWT_SECRET, JWT_ALG)
    db.add(RefreshToken(jti=refresh_jti, user_id=user.id, family_id=family_id,
                        issued_at=now, expires_at=refresh_exp))
    return schemas.TokenPair(access_token=access, refresh_token=refresh, expires_in=config.ACCESS_TTL_SECONDS)


def revoke_family(db: Session, family_id: str) -> None:
    db.execute(update(RefreshToken)
               .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=utcnow()))


def revoke_all_for_user(db: Session, user_id: int) -> None:
    db.execute(update(RefreshToken)
               .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=utcnow()))


def client_ip(request: Request) -> str | None:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else None)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok"}


@app.post("/register", response_model=schemas.UserOut, status_code=201)
def register(body: schemas.RegisterIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "Пользователь с таким email уже есть")
    user = User(email=email, full_name=body.full_name, password_hash=hash_password(body.password), role=DEFAULT_ROLE)
    db.add(user)
    try:
        db.flush()
        outbox.add(db, "user.registered", {"user_id": user.id, "email": user.email, "full_name": user.full_name})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Пользователь с таким email уже есть")
    return user


@app.post("/login", response_model=schemas.TokenPair)
def login(body: schemas.LoginIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower()
    since = utcnow() - timedelta(seconds=config.LOGIN_WINDOW_SECONDS)
    last_success = db.scalar(select(func.max(LoginEvent.created_at))
                             .where(LoginEvent.email == email, LoginEvent.success.is_(True)))
    if last_success and last_success > since:
        since = last_success
    failures = db.scalar(select(func.count()).select_from(LoginEvent).where(
        LoginEvent.email == email, LoginEvent.success.is_(False), LoginEvent.created_at > since))
    if failures >= config.LOGIN_MAX_FAILURES:
        raise HTTPException(429, "Слишком много неудачных попыток входа, попробуйте позже")

    user = db.scalar(select(User).where(User.email == email))
    password_ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    success = bool(user) and password_ok
    db.add(LoginEvent(email=email, user_id=user.id if user else None, success=success, ip=client_ip(request)))
    if not success:
        db.commit()
        raise HTTPException(401, "Неверный email или пароль")
    if not user.is_active:
        db.commit()
        raise HTTPException(403, "Учётная запись отключена")
    pair = issue_tokens(db, user)
    db.commit()
    return pair


@app.post("/refresh", response_model=schemas.TokenPair)
def refresh(body: schemas.RefreshIn, db: Session = Depends(get_db)):
    claims = decode_token(body.refresh_token, "refresh")
    row = db.get(RefreshToken, claims["jti"], with_for_update=True)
    if not row:
        raise HTTPException(401, "Неизвестный refresh-токен")
    if row.revoked_at:
        raise HTTPException(401, "Refresh-токен отозван")
    if row.used_at:
        # токен уже меняли на новый: кто-то повторяет старый, значит цепочка могла утечь
        revoke_family(db, row.family_id)
        db.commit()
        raise HTTPException(401, "Refresh-токен уже использован, сессия отозвана")
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        revoke_family(db, row.family_id)
        db.commit()
        raise HTTPException(401, "Учётная запись отключена")
    row.used_at = utcnow()
    pair = issue_tokens(db, user, row.family_id)
    db.commit()
    return pair


@app.post("/logout", status_code=204)
def logout(body: schemas.RefreshIn, db: Session = Depends(get_db)):
    claims = decode_token(body.refresh_token, "refresh")
    row = db.get(RefreshToken, claims["jti"])
    if row:
        revoke_family(db, row.family_id)
        db.commit()
    return Response(status_code=204)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@app.post("/password/forgot", status_code=202)
def forgot_password(body: schemas.ForgotPasswordIn, db: Session = Depends(get_db)):
    """Ответ одинаковый для любого email: по нему нельзя узнать, зарегистрирован ли адрес."""
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user and user.is_active:
        token = secrets.token_urlsafe(32)
        expires_at = utcnow() + timedelta(seconds=config.PASSWORD_RESET_TTL_SECONDS)
        db.add(PasswordReset(user_id=user.id, token_hash=_token_hash(token), expires_at=expires_at))
        # Токен едет в письмо через брокер. В проде лучше отдавать notifier'у не сам токен, а ссылку
        # на одноразовый объект; здесь компромисс ради простоты стенда.
        outbox.add(db, "user.password_reset", {"user_id": user.id, "email": user.email, "full_name": user.full_name,
                                               "reset_token": token, "expires_at": expires_at.isoformat()})
        db.commit()
    return {"detail": "Если такой email зарегистрирован, мы отправили письмо со ссылкой для сброса пароля"}


@app.post("/password/reset", status_code=204)
def reset_password(body: schemas.ResetPasswordIn, db: Session = Depends(get_db)):
    now = utcnow()
    reset = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == _token_hash(body.token))
                      .with_for_update())
    if not reset or reset.used_at or reset.expires_at <= now:
        raise HTTPException(400, "Ссылка для сброса недействительна или устарела")
    user = db.get(User, reset.user_id)
    user.password_hash = hash_password(body.new_password)
    # гасим и эту, и все остальные неиспользованные ссылки пользователя
    db.execute(update(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
               .values(used_at=now))
    revoke_all_for_user(db, user.id)
    db.commit()
    return Response(status_code=204)


@app.post("/internal/jobs/cleanup-tokens", dependencies=[Depends(require_service)])
def cleanup_tokens(db: Session = Depends(get_db)):
    """Ночная чистка: удаляет просроченные refresh-токены и ссылки сброса пароля."""
    now = utcnow()
    tokens = db.execute(delete(RefreshToken).where(RefreshToken.expires_at < now)).rowcount
    resets = db.execute(delete(PasswordReset).where(PasswordReset.expires_at < now)).rowcount
    db.commit()
    return {"refresh_tokens_deleted": tokens, "password_resets_deleted": resets}


@app.get("/me", response_model=schemas.UserOut)
def me(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    user = db.get(User, principal.user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    return user


@app.get("/users", response_model=list[schemas.UserOut])
def list_users(role: str | None = None, email: str | None = None,
               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
               db: Session = Depends(get_db), _: Principal = Depends(require("users.manage"))):
    query = select(User).order_by(User.id).limit(limit).offset(offset)
    if role:
        query = query.where(User.role == role)
    if email:
        query = query.where(User.email == email.lower())
    return db.scalars(query).all()


@app.get("/users/{user_id}", response_model=schemas.UserOut)
def get_user(user_id: int, db: Session = Depends(get_db), _: Principal = Depends(require("users.manage"))):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    return user


@app.patch("/users/{user_id}", response_model=schemas.UserOut)
def patch_user(user_id: int, body: schemas.UserPatch, db: Session = Depends(get_db),
               principal: Principal = Depends(require("users.manage"))):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    if body.role is not None and not db.get(Role, body.role):
        raise HTTPException(422, f"Нет роли {body.role}")
    if user.id == principal.user_id and (body.is_active is False or (body.role and body.role != user.role)):
        raise HTTPException(409, "Нельзя отключить себя или сменить себе роль")
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            revoke_all_for_user(db, user.id)
    db.commit()
    return user


@app.get("/roles", response_model=list[schemas.RoleOut])
def list_roles(db: Session = Depends(get_db), _: Principal = Depends(require("users.manage"))):
    return [schemas.RoleOut(name=r.name, title=r.title, permissions=role_permissions(db, r.name))
            for r in db.scalars(select(Role).order_by(Role.name))]
