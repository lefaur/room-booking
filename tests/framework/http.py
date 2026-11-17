"""HTTP-коннектор: один на все сервисы (ходим через gateway). Каждый вызов пишется в лог сценария:
behavex прикладывает его к HTML-отчёту и к Allure."""
import json
import logging
import threading

import requests

log = logging.getLogger("http")


class ApiClient:
    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url
        self.timeout = timeout
        self.history: list[requests.Response] = []
        self._lock = threading.Lock()
        self._local = threading.local()  # Session не потокобезопасна: у каждого потока своя

    @property
    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def request(self, method: str, path: str, *, token: str | None = None, json_body=None,
                params: dict | None = None, auth: tuple[str, str] | None = None) -> requests.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = self._session.request(method, self.base_url + path, json=json_body, params=params,
                                         headers=headers, auth=auth, timeout=self.timeout)
        with self._lock:
            self.history.append(response)
        log.info(self.describe(response))
        return response

    @staticmethod
    def describe(response: requests.Response) -> str:
        req = response.request
        body = req.body.decode() if isinstance(req.body, bytes) else req.body
        return (f"{req.method} {req.url}\n{_pretty(body) if body else ''}\n\n"
                f"<- {response.status_code} ({response.elapsed.total_seconds() * 1000:.0f} ms)\n"
                f"{_pretty(response.text)}")


def _pretty(text: str) -> str:
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except ValueError:
        return text
