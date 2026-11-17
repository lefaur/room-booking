"""Письма по событиям: (тема, текст). Нет нужного поля в payload → KeyError → сообщение уходит в DLQ."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8080")
OFFICE_TZ = ZoneInfo(os.getenv("OFFICE_TZ", "Europe/Moscow"))


def _when(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(OFFICE_TZ).strftime("%d.%m.%Y %H:%M")


def _booking_line(p: dict) -> str:
    return f"{p['resource_name']}: {_when(p['start'])} – {_when(p['end'])}"


def recipient(event: dict) -> str:
    payload = event["payload"]
    return payload.get("user_email") or payload["email"]


def render(event: dict) -> tuple[str, str]:
    p = event["payload"]
    kind = event["type"]
    if kind == "user.registered":
        return ("Добро пожаловать в OfficeSpace",
                f"{p['full_name']}, вы зарегистрированы. Войти: {PUBLIC_URL}/login")
    if kind == "user.password_reset":
        return ("Сброс пароля",
                f"Чтобы задать новый пароль, перейдите по ссылке до {_when(p['expires_at'])}:\n"
                f"{PUBLIC_URL}/reset-password?token={p['reset_token']}\n\n"
                "Если вы не запрашивали сброс, просто проигнорируйте письмо.")
    if kind == "booking.created":
        return (f"Подтвердите бронь: {p['resource_name']}",
                f"{_booking_line(p)}\nПодтвердите до {_when(p['confirm_until'])}, иначе бронь снимется.\n"
                f"{PUBLIC_URL}/bookings/{p['booking_id']}")
    if kind == "booking.confirmed":
        return f"Бронь подтверждена: {p['resource_name']}", _booking_line(p)
    if kind == "booking.cancelled":
        who = "вы" if p["by_owner"] else "руководитель или администратор"
        return f"Бронь отменена: {p['resource_name']}", f"{_booking_line(p)}\nОтменил(а): {who}."
    if kind == "booking.expired":
        return (f"Бронь не подтверждена и снята: {p['resource_name']}",
                f"{_booking_line(p)}\nВремя подтверждения вышло, ресурс снова свободен.")
    if kind == "booking.reminder":
        return (f"Напоминание: {p['resource_name']} в {_when(p['start'])[-5:]}",
                f"{_booking_line(p)}\nНе забудьте отметиться по приходу: {PUBLIC_URL}/bookings/{p['booking_id']}")
    if kind == "booking.no_show":
        return (f"Бронь снята: вы не отметились ({p['resource_name']})",
                f"{_booking_line(p)}\nОтметки не было, ресурс освобождён для коллег.")
    if kind == "telegram.linked":
        return "Telegram привязан", f"К аккаунту {p['user_email']} привязан Telegram. Если это были не вы, напишите в поддержку."
    raise KeyError(f"Нет шаблона для события {kind}")


ROUTING_KEYS = ["user.registered", "user.password_reset", "booking.created", "booking.confirmed",
                "booking.cancelled", "booking.expired", "booking.reminder", "booking.no_show", "telegram.linked"]
