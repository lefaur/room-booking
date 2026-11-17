"""Письма (Mailpit), события в RabbitMQ и сброс пароля."""
import re
import uuid

from behave import step

from framework import data
from framework.infra import envelope, wait_until
from framework.support import actor, expect

RESET_LINK = re.compile(r"reset-password\?token=([\w-]+)")


def _email(context, label: str) -> str:
    return actor(context, label, logged_in=False).email


# --- письма ---

@step('пользователю "{label}" приходит письмо «{subject}»')
def step_mail_arrives(context, label, subject):
    context.mail_message = context.mail.wait_for(_email(context, label), subject)


@step("в письме есть «{text}»")
def step_mail_contains(context, text):
    body = context.mail_message["Text"]
    assert text in body, f"В письме нет «{text}»:\n{body}"


@step('пользователю "{label}" пришло ровно {count:d} письмо «{subject}»')
@step('пользователю "{label}" пришло ровно {count:d} письма «{subject}»')
def step_mail_count(context, label, count, subject):
    actual = context.mail.count(_email(context, label), subject)
    assert actual == count, f"Писем «{subject}»: {actual}, ожидали {count}"


@step('пользователю "{label}" не приходило писем «{subject}»')
def step_no_mail(context, label, subject):
    step_mail_count(context, label, 0, subject)


# --- сброс пароля ---

@step('пользователь "{label}" запрашивает сброс пароля')
def step_forgot(context, label):
    context.resp = context.auth.forgot_password(_email(context, label))


@step('пользователь "{label}" запросил сброс пароля')
def step_forgot_done(context, label):
    email = _email(context, label)
    already = context.mail.count(email, "Сброс пароля")
    step_forgot(context, label)
    expect(context.resp, 202)
    context.mail_message = context.mail.wait_for(email, "Сброс пароля", count=already + 1)
    context.reset_tokens.append(RESET_LINK.search(context.mail_message["Text"]).group(1))
    context.reset_token = context.reset_tokens[-1]


@step("гость запрашивает сброс пароля для незарегистрированного email")
def step_forgot_unknown(context):
    context.unknown_email = data.unique_email("nobody")
    context.resp = context.auth.forgot_password(context.unknown_email)


@step("на незарегистрированный email писем нет")
def step_unknown_no_mail(context):
    assert context.mail.messages_to(context.unknown_email) == []


@step('по ссылке из письма задаётся пароль "{password}"')
def step_reset(context, password):
    context.resp = context.auth.reset_password(context.reset_token, password)


@step('по ссылке из письма задан пароль "{password}"')
def step_reset_done(context, password):
    step_reset(context, password)
    expect(context.resp, 204)


@step('по первой ссылке задаётся пароль "{password}"')
def step_reset_first(context, password):
    context.resp = context.auth.reset_password(context.reset_tokens[0], password)


@step('по неизвестной ссылке задаётся пароль "{password}"')
def step_reset_unknown(context, password):
    context.resp = context.auth.reset_password(uuid.uuid4().hex, password)


@step("ссылка для сброса создана {minutes:d} минут назад")
def step_age_reset(context, minutes):
    updated = context.db.execute(
        "UPDATE auth.password_resets SET created_at = created_at - make_interval(mins => %s), "
        "expires_at = expires_at - make_interval(mins => %s) "
        "WHERE token_hash = encode(sha256(convert_to(%s, 'UTF8')), 'hex')",
        (minutes, minutes, context.reset_token))
    assert updated == 1


@step('пользователь "{label}" теперь входит с паролем "{password}"')
def step_login_new_password(context, label, password):
    expect(context.auth.login(_email(context, label), password), 200)


@step('у пользователя "{label}" больше не работает старый пароль')
def step_old_password(context, label):
    person = actor(context, label, logged_in=False)
    expect(context.auth.login(person.email, person.password), 401)


# --- события в брокере ---

@step('в брокер публикуется событие "{event_type}" без email получателя')
def step_publish_broken(context, event_type):
    context.marker = data.uid()
    context.event = envelope(event_type, {"user_id": 0, "full_name": f"broken-{context.marker}"})
    context.rabbit.publish(event_type, context.event, message_id=context.event["event_id"])


@step('в брокер публикуется не-JSON сообщение с ключом "{routing_key}"')
def step_publish_garbage(context, routing_key):
    context.marker = data.uid()
    context.rabbit.publish(routing_key, f"not a json {context.marker}")


@step('сообщение оказывается в очереди "{queue}"')
def step_in_dlq(context, queue):
    def probe():
        return [m for m in context.rabbit.peek(queue) if context.marker in m["payload"]]
    found = wait_until(probe, message=f"Сообщение {context.marker} не попало в {queue}")
    context.dead_message = found[0]


@step('в брокер дважды публикуется событие "{event_type}" для нового email')
def step_publish_twice(context, event_type):
    context.dup_email = data.unique_email("dup")
    event = envelope(event_type, {"user_id": 0, "email": context.dup_email, "full_name": "Дубль"})
    for _ in range(2):
        context.rabbit.publish(event_type, event, message_id=event["event_id"])
    # третье событие идёт следом: notifier обрабатывает очередь по одному, поэтому когда придёт его письмо,
    # оба дубля уже точно обработаны — без слепого sleep
    context.marker_email = data.unique_email("marker")
    context.rabbit.publish(event_type, envelope(event_type, {"user_id": 0, "email": context.marker_email,
                                                              "full_name": "Маркер"}))


@step("на этот email пришло ровно одно письмо «{subject}»")
def step_dup_one(context, subject):
    context.mail.wait_for(context.marker_email, subject)
    actual = context.mail.count(context.dup_email, subject)
    assert actual == 1, f"Писем на {context.dup_email}: {actual}"


@step('в БД не осталось действующих refresh-токенов пользователя "{label}"')
def step_no_alive_refresh(context, label):
    row = context.db.one(
        "SELECT count(*) AS total, count(*) FILTER (WHERE revoked_at IS NULL) AS alive "
        "FROM auth.refresh_tokens WHERE user_id = %s", (context.users[label].id,))
    assert row["total"] >= 1 and row["alive"] == 0, row
