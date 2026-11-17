"""Клиенты вспомогательных систем стенда: почтовый ящик Mailpit, RabbitMQ (management API)
и заглушки внешних сервисов. Через них тесты видят то, что сервисы отправляют наружу."""
import json
import time
import uuid
from datetime import datetime, timezone

from framework.config import RabbitConfig
from framework.http import ApiClient


def wait_until(probe, timeout: float = 10, interval: float = 0.3, message: str = "Условие не выполнилось"):
    """Повторяет probe(), пока он не вернёт что-то истинное. Асинхронные эффекты (письма, сообщения в боте)
    проверяем только так: фиксированный sleep либо медленный, либо ненадёжный."""
    deadline = time.monotonic() + timeout
    while True:
        result = probe()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise AssertionError(f"{message} за {timeout} с")
        time.sleep(interval)


class Mailpit:
    def __init__(self, url: str, timeout: float):
        self.http = ApiClient(url, timeout)

    def messages_to(self, email: str) -> list[dict]:
        """Письма адресату, от старых к новым."""
        resp = self.http.request("GET", "/api/v1/search", params={"query": f'to:"{email}"', "limit": 50})
        resp.raise_for_status()
        return list(reversed(resp.json()["messages"]))

    def message(self, message_id: str) -> dict:
        resp = self.http.request("GET", f"/api/v1/message/{message_id}")
        resp.raise_for_status()
        return resp.json()

    def wait_for(self, email: str, subject: str, timeout: float = 10, count: int = 1) -> dict:
        """Ждёт, пока писем с такой темой станет не меньше count, и возвращает последнее."""
        def probe():
            found = [m for m in self.messages_to(email) if subject.lower() in m["Subject"].lower()]
            return found[-1] if len(found) >= count else None
        summary = wait_until(probe, timeout, message=f"Письмо «{subject}» не пришло на {email}")
        return self.message(summary["ID"])

    def count(self, email: str, subject: str) -> int:
        return sum(subject.lower() in m["Subject"].lower() for m in self.messages_to(email))


class RabbitAdmin:
    """Management API RabbitMQ: публикация «руками» и подсматривание в очереди."""

    def __init__(self, cfg: RabbitConfig, timeout: float):
        self.http = ApiClient(cfg.url, timeout)
        self.auth = (cfg.user, cfg.password)

    def publish(self, routing_key: str, body: str | dict, message_id: str | None = None) -> None:
        payload = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        resp = self.http.request("POST", "/api/exchanges/%2F/officespace.events/publish", auth=self.auth, json_body={
            "routing_key": routing_key, "payload": payload, "payload_encoding": "string",
            "properties": {"content_type": "application/json", "delivery_mode": 2,
                           "message_id": message_id or str(uuid.uuid4())}})
        resp.raise_for_status()
        assert resp.json()["routed"], f"Сообщение с ключом {routing_key} никуда не попало"

    def peek(self, queue: str, count: int = 500) -> list[dict]:
        """Читает сообщения и возвращает их обратно в очередь: соседние сценарии ничего не теряют."""
        resp = self.http.request("POST", f"/api/queues/%2F/{queue}/get", auth=self.auth, json_body={
            "count": count, "ackmode": "ack_requeue_true", "encoding": "auto"})
        resp.raise_for_status()
        return resp.json()

    def queue(self, name: str) -> dict:
        resp = self.http.request("GET", f"/api/queues/%2F/{name}", auth=self.auth)
        resp.raise_for_status()
        return resp.json()


def envelope(event_type: str, payload: dict, event_id: str | None = None) -> dict:
    """Конверт события в том виде, в каком его публикует outbox сервисов."""
    return {"event_id": event_id or str(uuid.uuid4()), "type": event_type, "source": "autotest",
            "occurred_at": datetime.now(timezone.utc).isoformat(), "payload": payload}


class Stubs:
    def __init__(self, url: str, timeout: float):
        self.http = ApiClient(url, timeout)

    # Telegram
    def user_writes(self, chat_id: int, text: str) -> None:
        self.http.request("POST", "/_control/telegram/messages",
                          json_body={"chat_id": chat_id, "text": text}).raise_for_status()

    def user_presses(self, chat_id: int, data: str) -> dict:
        resp = self.http.request("POST", "/_control/telegram/callbacks", json_body={"chat_id": chat_id, "data": data})
        resp.raise_for_status()
        return resp.json()["callback_query"]

    def bot_messages(self, chat_id: int) -> list[dict]:
        resp = self.http.request("GET", "/_control/telegram/sent", params={"chat_id": chat_id})
        resp.raise_for_status()
        return resp.json()

    def callback_answer(self, callback_id: str) -> dict | None:
        resp = self.http.request("GET", "/_control/telegram/callback-answers")
        resp.raise_for_status()
        return next((a for a in resp.json() if a.get("callback_query_id") == callback_id), None)

    # производственный календарь
    def set_calendar(self, mode: str = "ok", days: dict[int, list[dict]] | None = None) -> None:
        self.http.request("PUT", "/_control/calendar", json_body={"mode": mode, "days": days}).raise_for_status()

    def reset_calendar(self) -> None:
        self.http.request("DELETE", "/_control/calendar").raise_for_status()
