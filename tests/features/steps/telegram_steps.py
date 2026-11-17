"""Telegram-бот: пользователь пишет и жмёт кнопки через заглушку Bot API, ответы бота читаем оттуда же."""
import json
import random

from behave import step

from framework import models
from framework.infra import wait_until
from framework.support import actor, expect, parse


def _chat(context, label: str) -> int:
    """У каждого участника свой чат: случайный id, чтобы параллельные сценарии не пересекались."""
    chats = context.chats
    if label not in chats:
        chats[label] = random.randint(10**9, 10**12)
    return chats[label]


def _wait_bot_message(context, label: str, text: str) -> dict:
    chat = _chat(context, label)

    def probe():
        found = [m for m in context.stubs.bot_messages(chat) if text.lower() in m["text"].lower()]
        return found[-1] if found else None
    return wait_until(probe, message=f"Бот не написал «{text}» в чат «{label}»")


@step('пользователь "{label}" получил код привязки')
def step_link_code(context, label):
    resp = expect(context.tg.create_code(actor(context, label).access_token), 201)
    context.link_code = parse(models.LinkCode, resp)


@step('пользователь "{label}" отправляет боту "{text}"')
def step_user_writes(context, label, text):
    context.stubs.user_writes(_chat(context, label), text)


@step('пользователь "{label}" отправляет боту свой код')
@step('пользователь "{label}" отправляет боту тот же код')
def step_user_sends_code(context, label):
    step_user_writes(context, label, context.link_code.command)


@step('пользователь "{label}" привязал Telegram')
def step_linked(context, label):
    step_link_code(context, label)
    step_user_sends_code(context, label)
    _wait_bot_message(context, label, "привязан")


@step('бот отвечает пользователю "{label}" «{text}»')
@step('бот пишет пользователю "{label}" «{text}»')
def step_bot_says(context, label, text):
    context.bot_message = _wait_bot_message(context, label, text)


@step("под сообщением кнопки {buttons}")
def step_buttons(context, buttons):
    markup = json.loads(context.bot_message["reply_markup"] or "{}")
    actual = [b["text"] for row in markup.get("inline_keyboard", []) for b in row]
    expected = [b.strip(" «»") for b in buttons.split(",")]
    assert actual == expected, f"Кнопки {actual}, ожидали {expected}"


@step('пользователь "{label}" нажимает кнопку «{button}»')
def step_press(context, label, button):
    markup = json.loads(context.bot_message["reply_markup"])
    data = next(b["callback_data"] for row in markup["inline_keyboard"] for b in row if b["text"] == button)
    context.callback = context.stubs.user_presses(_chat(context, label), data)


@step('пользователь "{label}" нажимает кнопку с данными "{data}"')
def step_press_raw(context, label, data):
    booking_id = context.bookings[-1].id if context.bookings else 0
    context.callback = context.stubs.user_presses(_chat(context, label), data.format(id=booking_id))


@step("бот отвечает на нажатие «{text}»")
def step_callback_answer(context, text):
    answer = wait_until(lambda: context.stubs.callback_answer(context.callback["id"]),
                        message="Бот не ответил на нажатие кнопки")
    assert text.lower() in answer["text"].lower(), f"Ответ на нажатие: {answer}"


@step('в приложении у пользователя "{label}" Telegram {state}')
def step_link_state(context, label, state):
    resp = context.tg.get_link(actor(context, label).access_token)
    if state == "привязан":
        assert expect(resp, 200).json()["chat_id"] == _chat(context, label)
    else:
        expect(resp, 404)


@step('пользователь "{label}" отвязывает Telegram')
def step_unlink(context, label):
    context.resp = context.tg.unlink(actor(context, label).access_token)


@step('пользователю "{label}" бот ничего не писал о брони')
def step_no_bot_message(context, label):
    booking_id = context.bookings[-1].id
    messages = [m for m in context.stubs.bot_messages(_chat(context, label)) if f"#{booking_id}" in m["text"]]
    assert not messages, messages
