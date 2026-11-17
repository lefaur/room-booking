"""Сервис tgbot: привязка Telegram к аккаунту, уведомления о бронях с кнопками, команды /my и /help.

Три потока в одном процессе: HTTP API (привязка), опрос Telegram (getUpdates) и потребитель событий из RabbitMQ.
"""
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, HTTPException, Response
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.messaging import consume_forever, utcnow
from common.security import SERVICE_TOKEN, Principal, current_principal
from tgbot import telegram
from tgbot.db import Base, Link, LinkCode, ProcessedEvent, SessionLocal, engine, get_db, outbox

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("tgbot")

ROOT_PATH = os.getenv("ROOT_PATH", "")
BOOKING_URL = os.getenv("BOOKING_INTERNAL_URL", "http://localhost:8002")
OFFICE_TZ = ZoneInfo(os.getenv("OFFICE_TZ", "Europe/Moscow"))
LINK_CODE_TTL = timedelta(minutes=int(os.getenv("LINK_CODE_TTL_MINUTES", "10")))
POLLING = os.getenv("TELEGRAM_POLLING", "1") == "1"

HELP = ("Я бот OfficeSpace.\n"
        "/start <код> — привязать аккаунт (код выдаётся в приложении)\n"
        "/my — мои ближайшие брони\n"
        "/help — эта справка")


def _when(value: str | datetime) -> str:
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    return moment.astimezone(OFFICE_TZ).strftime("%d.%m %H:%M")


# --- HTTP API ---

@asynccontextmanager
async def lifespan(_: FastAPI):
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS tgbot"))
    Base.metadata.create_all(engine)
    outbox.start_relay()
    if POLLING:
        threading.Thread(target=poll_forever, name="telegram-poller", daemon=True).start()
    threading.Thread(target=consume_forever, name="events-consumer", daemon=True,
                     args=("tgbot", list(NOTIFICATIONS), handle_event)).start()
    yield


app = FastAPI(title="OfficeSpace · tgbot", root_path=ROOT_PATH, lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/link-code", status_code=201)
def create_link_code(db: Session = Depends(get_db), principal: Principal = Depends(current_principal)):
    """Новый код гасит предыдущие неиспользованные коды пользователя."""
    db.execute(delete(LinkCode).where(LinkCode.user_id == principal.user_id, LinkCode.used_at.is_(None)))
    code = LinkCode(code=secrets.token_hex(4).upper(), user_id=principal.user_id, user_email=principal.email,
                    expires_at=utcnow() + LINK_CODE_TTL)
    db.add(code)
    db.commit()
    return {"code": code.code, "expires_at": code.expires_at, "command": f"/start {code.code}"}


@app.get("/link")
def get_link(db: Session = Depends(get_db), principal: Principal = Depends(current_principal)):
    link = db.get(Link, principal.user_id)
    if not link:
        raise HTTPException(404, "Telegram не привязан")
    return {"chat_id": link.chat_id, "username": link.username, "linked_at": link.linked_at}


@app.delete("/link", status_code=204)
def delete_link(db: Session = Depends(get_db), principal: Principal = Depends(current_principal)):
    if not db.get(Link, principal.user_id):
        raise HTTPException(404, "Telegram не привязан")
    db.execute(delete(Link).where(Link.user_id == principal.user_id))
    db.commit()
    return Response(status_code=204)


# --- входящие сообщения и кнопки ---

def booking_call(method: str, path: str, **params) -> httpx.Response:
    return httpx.request(method, f"{BOOKING_URL}{path}", params=params, timeout=10,
                         headers={"X-Service-Token": SERVICE_TOKEN})


def link_by_chat(db: Session, chat_id: int) -> Link | None:
    return db.scalar(select(Link).where(Link.chat_id == chat_id))


def cmd_start(db: Session, chat_id: int, username: str | None, arg: str) -> str:
    if not arg:
        return "Чтобы привязать аккаунт, получите код в приложении и отправьте: /start <код>\n\n" + HELP
    code = db.scalar(select(LinkCode).where(LinkCode.code == arg.strip().upper()).with_for_update())
    if not code or code.used_at or code.expires_at <= utcnow():
        return "Код недействителен или устарел. Получите новый в приложении."
    other = link_by_chat(db, chat_id)
    if other and other.user_id != code.user_id:
        return f"Этот чат уже привязан к {other.user_email}. Сначала отвяжите его в приложении."
    code.used_at = utcnow()
    db.execute(delete(Link).where(Link.user_id == code.user_id))
    db.add(Link(user_id=code.user_id, user_email=code.user_email, chat_id=chat_id, username=username))
    outbox.add(db, "telegram.linked", {"user_id": code.user_id, "user_email": code.user_email, "chat_id": chat_id})
    db.commit()
    return f"Готово! Аккаунт {code.user_email} привязан. Сюда будут приходить уведомления о бронях."


def cmd_my(db: Session, chat_id: int) -> str:
    link = link_by_chat(db, chat_id)
    if not link:
        return "Аккаунт не привязан. Отправьте /start <код> из приложения."
    response = booking_call("GET", "/internal/bookings", user_id=link.user_id)
    response.raise_for_status()
    rows = response.json()
    if not rows:
        return "Активных броней нет."
    lines = [f"#{r['booking_id']} {r['resource_name']}: {_when(r['start'])} – {_when(r['end'])} [{STATUS[r['status']]}]"
             for r in rows]
    return "Ваши брони:\n" + "\n".join(lines)


STATUS = {"pending": "ждёт подтверждения", "confirmed": "подтверждена", "checked_in": "вы на месте"}
ACTIONS = {"confirm": "Бронь подтверждена", "cancel": "Бронь отменена", "check-in": "Отметка принята"}


def handle_message(db: Session, message: dict) -> None:
    chat_id = message["chat"]["id"]
    command, _, arg = (message.get("text") or "").strip().partition(" ")
    if command == "/start":
        reply = cmd_start(db, chat_id, message.get("from", {}).get("username"), arg)
    elif command == "/my":
        reply = cmd_my(db, chat_id)
    else:
        reply = HELP
    telegram.send_message(chat_id, reply)


def handle_callback(db: Session, callback: dict) -> None:
    chat_id = callback["message"]["chat"]["id"]
    action, _, booking_id = (callback.get("data") or "").partition(":")
    link = link_by_chat(db, chat_id)
    if action not in ACTIONS or not booking_id.isdigit():
        telegram.answer_callback(callback["id"], "Неизвестная команда", alert=True)
        return
    if not link:
        telegram.answer_callback(callback["id"], "Аккаунт не привязан", alert=True)
        return
    response = booking_call("POST", f"/internal/bookings/{booking_id}/{action}", user_id=link.user_id)
    if response.status_code == 200:
        telegram.answer_callback(callback["id"], ACTIONS[action])
    else:
        detail = response.json().get("detail", "Ошибка") if response.headers.get("content-type", "").startswith(
            "application/json") else "Сервис недоступен"
        telegram.answer_callback(callback["id"], str(detail), alert=True)


def poll_forever() -> None:
    offset = 0
    while True:
        try:
            for update in telegram.get_updates(offset):
                offset = update["update_id"] + 1
                with SessionLocal() as db:
                    try:
                        if "message" in update:
                            handle_message(db, update["message"])
                        elif "callback_query" in update:
                            handle_callback(db, update["callback_query"])
                    except Exception:  # noqa: BLE001 — один плохой апдейт не должен останавливать бота
                        db.rollback()
                        log.exception("ошибка обработки апдейта %s", update["update_id"])
        except Exception:  # noqa: BLE001
            log.exception("getUpdates не удался, повтор через 1 с")
            time.sleep(1)


# --- уведомления из RabbitMQ ---

def _line(p: dict) -> str:
    return f"{p['resource_name']}, {_when(p['start'])} – {_when(p['end'])}"


def _created(p):
    return (f"Новая бронь #{p['booking_id']}: {_line(p)}\nПодтвердите до {_when(p['confirm_until'])}",
            [("Подтвердить", f"confirm:{p['booking_id']}"), ("Отменить", f"cancel:{p['booking_id']}")])


def _reminder(p):
    return (f"Скоро начало: {_line(p)}\nОтметьтесь, когда придёте",
            [("Я на месте", f"check-in:{p['booking_id']}"), ("Отменить", f"cancel:{p['booking_id']}")])


NOTIFICATIONS = {
    "booking.created": _created,
    "booking.confirmed": lambda p: (f"Бронь #{p['booking_id']} подтверждена: {_line(p)}",
                                    [("Отменить", f"cancel:{p['booking_id']}")]),
    "booking.reminder": _reminder,
    "booking.cancelled": lambda p: (f"Бронь #{p['booking_id']} отменена: {_line(p)}", None),
    "booking.expired": lambda p: (f"Бронь #{p['booking_id']} не подтверждена и снята: {_line(p)}", None),
    "booking.no_show": lambda p: (f"Бронь #{p['booking_id']} снята, вы не отметились: {_line(p)}", None),
}


def handle_event(event: dict) -> None:
    with SessionLocal() as db:
        if db.get(ProcessedEvent, event["event_id"]):
            return
        payload = event["payload"]
        text_, buttons = NOTIFICATIONS[event["type"]](payload)
        link = db.get(Link, payload["user_id"])
        if link:  # не привязан — просто отмечаем событие обработанным
            telegram.send_message(link.chat_id, text_, buttons)
        db.add(ProcessedEvent(event_id=event["event_id"], event_type=event["type"]))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
