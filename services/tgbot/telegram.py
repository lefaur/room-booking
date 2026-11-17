"""Минимальный клиент Telegram Bot API. В стенде TELEGRAM_API_URL указывает на заглушку."""
import json
import os

import httpx

API_URL = os.getenv("TELEGRAM_API_URL", "https://api.telegram.org")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "123456:stub-token")


class TelegramError(Exception):
    pass


def call(method: str, http_timeout: float = 10, **params) -> dict | list | bool:
    params = {k: v for k, v in params.items() if v is not None}
    if isinstance(params.get("reply_markup"), dict):
        params["reply_markup"] = json.dumps(params["reply_markup"], ensure_ascii=False)
    response = httpx.post(f"{API_URL}/bot{BOT_TOKEN}/{method}", json=params, timeout=http_timeout)
    data = response.json()
    if not data.get("ok"):
        raise TelegramError(f"{method}: {data.get('description', response.status_code)}")
    return data["result"]


def send_message(chat_id: int, text: str, buttons: list[tuple[str, str]] | None = None) -> dict:
    markup = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in buttons]]} if buttons else None
    return call("sendMessage", chat_id=chat_id, text=text, reply_markup=markup)


def answer_callback(callback_id: str, text: str, alert: bool = False) -> None:
    call("answerCallbackQuery", callback_query_id=callback_id, text=text, show_alert=alert)


def get_updates(offset: int, timeout: int = 1) -> list[dict]:
    return call("getUpdates", http_timeout=timeout + 5, offset=offset, timeout=timeout)
