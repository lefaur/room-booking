"""Заглушки внешних систем для стенда. Состояние в памяти, тесты управляют им через /_control/*.

Telegram Bot API (подмножество): getUpdates, sendMessage, answerCallbackQuery.
Производственный календарь: GET /calendar/{year} с режимами ok / error / garbage / slow.
"""
import asyncio
import itertools
import os
import threading
import time
from datetime import date, timedelta
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "123456:stub-token")

app = FastAPI(title="OfficeSpace · stubs")
_lock = threading.Lock()


# --- Telegram ---

class TelegramState:
    def __init__(self):
        self.updates: list[dict] = []
        self.sent: list[dict] = []
        self.callback_answers: list[dict] = []
        self.update_ids = itertools.count(1)
        self.message_ids = itertools.count(1)
        self.callback_ids = itertools.count(1)


tg = TelegramState()


def _check_token(token: str) -> None:
    if token != BOT_TOKEN:
        raise HTTPException(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})


async def _params(request: Request) -> dict:
    params = dict(request.query_params)
    if request.headers.get("content-type", "").startswith("application/json"):
        params.update(await request.json())
    return params


@app.api_route("/telegram/bot{token}/getUpdates", methods=["GET", "POST"])
async def get_updates(token: str, request: Request):
    _check_token(token)
    params = await _params(request)
    offset = int(params.get("offset", 0))
    timeout = min(float(params.get("timeout", 0)), 1.0)  # long polling, но не дольше секунды
    deadline = time.monotonic() + timeout
    while True:
        with _lock:
            # как в настоящем API: offset подтверждает всё, что меньше него
            tg.updates = [u for u in tg.updates if u["update_id"] >= offset]
            result = list(tg.updates)
        if result or time.monotonic() >= deadline:
            return {"ok": True, "result": result}
        await asyncio.sleep(0.05)


@app.post("/telegram/bot{token}/sendMessage")
async def send_message(token: str, request: Request):
    _check_token(token)
    params = await _params(request)
    if "chat_id" not in params or not params.get("text"):
        return JSONResponse({"ok": False, "error_code": 400, "description": "Bad Request: message text is empty"}, 400)
    with _lock:
        message = {"message_id": next(tg.message_ids), "chat": {"id": int(params["chat_id"]), "type": "private"},
                   "date": int(time.time()), "text": params["text"], "reply_markup": params.get("reply_markup")}
        tg.sent.append(message)
    return {"ok": True, "result": message}


@app.post("/telegram/bot{token}/answerCallbackQuery")
async def answer_callback(token: str, request: Request):
    _check_token(token)
    params = await _params(request)
    with _lock:
        tg.callback_answers.append(params)
    return {"ok": True, "result": True}


class UserMessage(BaseModel):
    chat_id: int
    text: str
    username: str = "tester"


class ButtonPress(BaseModel):
    chat_id: int
    data: str
    message_id: int | None = None


@app.post("/_control/telegram/messages")
def push_message(body: UserMessage):
    """Пользователь пишет боту."""
    with _lock:
        update = {"update_id": next(tg.update_ids), "message": {
            "message_id": next(tg.message_ids), "date": int(time.time()), "text": body.text,
            "chat": {"id": body.chat_id, "type": "private"},
            "from": {"id": body.chat_id, "is_bot": False, "username": body.username}}}
        tg.updates.append(update)
    return update


@app.post("/_control/telegram/callbacks")
def push_callback(body: ButtonPress):
    """Пользователь нажимает инлайн-кнопку под сообщением бота."""
    with _lock:
        update = {"update_id": next(tg.update_ids), "callback_query": {
            "id": str(next(tg.callback_ids)), "data": body.data,
            "from": {"id": body.chat_id, "is_bot": False},
            "message": {"message_id": body.message_id or 0, "chat": {"id": body.chat_id, "type": "private"}}}}
        tg.updates.append(update)
    return update


@app.get("/_control/telegram/sent")
def sent_messages(chat_id: int):
    with _lock:
        return [m for m in tg.sent if m["chat"]["id"] == chat_id]


@app.get("/_control/telegram/callback-answers")
def callback_answers():
    with _lock:
        return list(tg.callback_answers)


# --- производственный календарь ---

FIXED_HOLIDAYS = [((1, d), "Новогодние каникулы") for d in range(1, 9)] + [
    ((2, 23), "День защитника Отечества"), ((3, 8), "Международный женский день"),
    ((5, 1), "Праздник Весны и Труда"), ((5, 9), "День Победы"), ((6, 12), "День России"),
    ((11, 4), "День народного единства")]


def default_year(year: int) -> dict:
    days = [{"date": date(year, m, d).isoformat(), "type": "holiday", "title": title}
            for (m, d), title in FIXED_HOLIDAYS]
    days += [{"date": (date(year, m, d) - timedelta(days=1)).isoformat(), "type": "short", "title": "Предпраздничный"}
             for (m, d), _ in FIXED_HOLIDAYS[8:] if (date(year, m, d) - timedelta(days=1)).weekday() < 5]
    return {"year": year, "days": days}


class CalendarState:
    def __init__(self):
        self.mode: str = "ok"
        self.overrides: dict[int, list[dict]] = {}
        self.requests: int = 0


calendar = CalendarState()


class CalendarControl(BaseModel):
    mode: Literal["ok", "error", "garbage", "slow"] = "ok"
    days: dict[int, list[dict]] | None = None   # год → дни, заменяют стандартные данные этого года


@app.get("/calendar/{year}")
async def calendar_year(year: int):
    with _lock:
        calendar.requests += 1
        mode, days = calendar.mode, calendar.overrides.get(year)
    if mode == "error":
        return JSONResponse({"error": "internal error"}, 500)
    if mode == "garbage":
        return PlainTextResponse("<html>Технические работы</html>")
    if mode == "slow":
        await asyncio.sleep(10)
    return {"year": year, "days": days} if days is not None else default_year(year)


@app.put("/_control/calendar")
def control_calendar(body: CalendarControl):
    with _lock:
        calendar.mode = body.mode
        calendar.overrides = body.days or {}
    return {"mode": calendar.mode, "years": sorted(calendar.overrides)}


@app.delete("/_control/calendar")
def reset_calendar():
    with _lock:
        calendar.mode, calendar.overrides = "ok", {}
    return {"mode": "ok"}


@app.get("/_control/calendar")
def calendar_state():
    with _lock:
        return {"mode": calendar.mode, "years": sorted(calendar.overrides), "requests": calendar.requests}


@app.get("/health")
def health():
    return {"status": "ok"}
