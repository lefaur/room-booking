from datetime import datetime, timedelta, timezone

import jwt
from behave import step

from framework import data, models
from framework.support import actor, expect, parse


# --- регистрация ---

@step('гость регистрируется с паролем "{password}"')
def step_guest_registers(context, password):
    context.guest_email = data.unique_email("guest")
    context.guest_password = password
    context.resp = context.auth.register(context.guest_email, password, "Гость")


@step('гость регистрируется с email пользователя "{label}" в верхнем регистре')
def step_guest_registers_duplicate(context, label):
    email = context.users[label].email.upper()
    context.resp = context.auth.register(email, data.PASSWORD, "Двойник")


@step('в ответе пользователь с ролью "{role}"')
def step_user_role(context, role):
    user = parse(models.User, context.resp)
    assert user.role == role, f"Роль {user.role}, ожидали {role}"
    assert user.email == context.guest_email


@step("в БД пароль пользователя хранится как хеш, а не открытым текстом")
def step_password_hashed(context):
    row = context.db.one("SELECT password_hash FROM auth.users WHERE email = %s", (context.guest_email,))
    assert row, "Пользователя нет в БД"
    assert row["password_hash"].startswith("pbkdf2_sha256$"), row["password_hash"]
    assert context.guest_password not in row["password_hash"]


# --- участники ---

@step('зарегистрирован пользователь "{label}"')
def step_registered(context, label):
    actor(context, label, logged_in=False)


@step('пользователь "{label}" вошёл в систему')
def step_logged_in(context, label):
    actor(context, label)


@step('администратор отключил пользователя "{label}"')
def step_admin_disables(context, label):
    person = actor(context, label, logged_in=False)
    expect(context.auth.patch_user(context.admin.token, person.id, is_active=False), 200)


@step('администратор назначил пользователю "{label}" роль "{role}"')
def step_admin_sets_role(context, label, role):
    person = actor(context, label, logged_in=False)
    expect(context.auth.patch_user(context.admin.token, person.id, role=role), 200)


@step('пользователь "{label}" отключает сам себя')
def step_disable_self(context, label):
    person = actor(context, label)
    context.resp = context.auth.patch_user(person.access_token, person.id, is_active=False)


# --- вход ---

@step('пользователь "{label}" входит с верным паролем')
def step_login_ok(context, label):
    person = actor(context, label, logged_in=False)
    context.resp = context.auth.login(person.email, person.password)


@step('пользователь "{label}" успешно вошёл')
def step_login_success(context, label):
    step_login_ok(context, label)
    expect(context.resp, 200)


@step('пользователь "{label}" входит с паролем "{password}"')
def step_login_with(context, label, password):
    person = actor(context, label, logged_in=False)
    context.resp = context.auth.login(person.email, password)


@step("гость входит с неизвестным email")
def step_login_unknown(context):
    context.resp = context.auth.login(data.unique_email("nobody"), data.PASSWORD)


@step('пользователь "{label}" ввёл неверный пароль, попыток: {count:d}')
def step_failed_logins(context, label, count):
    person = actor(context, label, logged_in=False)
    for _ in range(count):
        expect(context.auth.login(person.email, "Wrong12345"), 401)


@step("в ответе пара токенов, access живёт {seconds:d} секунд")
def step_token_pair(context, seconds):
    pair = parse(models.TokenPair, context.resp)
    assert pair.expires_in == seconds, f"expires_in={pair.expires_in}"
    claims = jwt.decode(pair.access_token, options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == seconds, claims
    context.access_claims = claims


@step('в access-токене роль "{role}" и права "{perms}"')
def step_token_claims(context, role, perms):
    claims = context.access_claims
    assert claims["role"] == role, claims
    assert claims["perms"] == [p.strip() for p in perms.split(",")], claims


@step('в журнале входов есть {kind} запись пользователя "{label}"')
def step_login_journal(context, kind, label):
    expected = {"успешная": True, "неуспешная": False}[kind]
    row = context.db.one(
        "SELECT success, user_id, ip FROM auth.login_events WHERE email = %s ORDER BY id DESC LIMIT 1",
        (context.users[label].email,))
    assert row, "В журнале входов нет записей"
    assert row["success"] is expected, row
    assert row["user_id"] == context.users[label].id, row
    assert row["ip"], "Не записан IP клиента"


# --- токены ---

@step('пользователь "{label}" обновляет токены')
def step_refresh(context, label):
    person = actor(context, label)
    context.previous_refresh = person.refresh_token
    context.resp = context.auth.refresh(person.refresh_token)
    if context.resp.status_code == 200:
        tokens = parse(models.TokenPair, context.resp)
        person.access_token, person.refresh_token = tokens.access_token, tokens.refresh_token


@step('пользователь "{label}" обновил токены')
def step_refreshed(context, label):
    step_refresh(context, label)
    expect(context.resp, 200)


@step('refresh-токен пользователя "{label}" сменился')
def step_refresh_changed(context, label):
    assert context.users[label].refresh_token != context.previous_refresh


@step('новый access-токен пользователя "{label}" работает')
def step_new_access_works(context, label):
    expect(context.auth.me(context.users[label].access_token), 200)


@step('пользователь "{label}" повторно отправляет первый refresh-токен')
def step_reuse_refresh(context, label):
    context.resp = context.auth.refresh(context.users[label].first_refresh_token)


@step('в БД все refresh-токены пользователя "{label}" отозваны')
def step_all_revoked(context, label):
    row = context.db.one(
        "SELECT count(*) AS total, count(*) FILTER (WHERE revoked_at IS NULL) AS alive "
        "FROM auth.refresh_tokens WHERE user_id = %s", (context.users[label].id,))
    assert row["total"] >= 2 and row["alive"] == 0, row


@step('пользователь "{label}" не может обновить токены')
def step_cannot_refresh(context, label):
    expect(context.auth.refresh(context.users[label].refresh_token), 401)


@step('пользователь "{label}" вышел из системы')
def step_logout(context, label):
    expect(context.auth.logout(actor(context, label).refresh_token), 204)


@step('пользователь "{label}" запрашивает профиль с токеном "{case}"')
def step_me_with_bad_token(context, label, case):
    person = actor(context, label)
    claims = jwt.decode(person.access_token, options={"verify_signature": False})
    if case == "просроченный":
        now = datetime.now(timezone.utc)
        token = jwt.encode({**claims, "iat": now - timedelta(minutes=16), "exp": now - timedelta(seconds=1)},
                           context.cfg.jwt_secret, "HS256")
    elif case == "чужая подпись":
        token = jwt.encode(claims, "not-our-secret-but-long-enough-for-hs256", "HS256")
    elif case == "refresh вместо access":
        token = person.refresh_token
    elif case == "без токена":
        token = None
    else:
        raise ValueError(f"Неизвестный случай: {case}")
    context.resp = context.auth.me(token)


# --- права ---

ACTIONS = {
    "список пользователей": lambda ctx, token: ctx.auth.list_users(token, limit=1),
    "создать этаж": lambda ctx, token: ctx.booking.create_floor(
        token, name=data.unique_name("perm-floor"), level=1, width=100, height=100),
    "изменить правила": lambda ctx, token: ctx.booking.put_settings(token),  # пустое тело: ничего не меняет
    "смотреть все брони": lambda ctx, token: ctx.booking.list_bookings(token, scope="all", limit=1),
    "запустить джобу просрочки": lambda ctx, token: ctx.booking.run_expire_job(token),
}


@step('пользователь "{label}" выполняет действие "{action}"')
def step_action(context, label, action):
    context.resp = ACTIONS[action](context, actor(context, label).access_token)
