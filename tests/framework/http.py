"""HTTP-коннектор: один на все сервисы (ходим через gateway). Каждый вызов пишется в лог сценария
(behavex прикладывает его к Allure) вместе с готовой curl-командой: запрос из упавшего теста
повторяется копированием в терминал.

Повторы — только там, где они не меняют смысл проверки: нет соединения (сервис перезапускается)
и 502/503/504 от gateway на идемпотентных методах. POST не повторяется по ответу: повтор создал бы
вторую бронь, и тест проверял бы уже не то. Ответ 4xx/500 не повторяется никогда — это результат.
"""
import json
import logging
import shlex
import threading
from collections.abc import Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("http")

RETRY = Retry(
    total=3, connect=3, read=0, status=3, backoff_factor=0.3,
    status_forcelist=(502, 503, 504),
    allowed_methods=frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}),
    raise_on_status=False,
)


class ApiClient:
    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url
        self.timeout = timeout
        self.history: list[requests.Response] = []
        self.on_response: Callable[[requests.Response], None] | None = None  # уборка узнаёт созданное
        self._lock = threading.Lock()
        self._local = threading.local()  # Session не потокобезопасна: у каждого потока своя

    @property
    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            session = requests.Session()
            session.mount("http://", HTTPAdapter(max_retries=RETRY))
            session.mount("https://", HTTPAdapter(max_retries=RETRY))
            self._local.session = session
        return self._local.session

    def request(self, method: str, path: str, *, token: str | None = None, json_body=None,
                params: dict | None = None, auth: tuple[str, str] | None = None) -> requests.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = self._session.request(method, self.base_url + path, json=json_body, params=params,
                                         headers=headers, auth=auth, timeout=self.timeout)
        with self._lock:
            self.history.append(response)
        log.info(self.describe(response))
        if self.on_response:
            self.on_response(response)
        return response

    @staticmethod
    def describe(response: requests.Response) -> str:
        req = response.request
        body = req.body.decode() if isinstance(req.body, bytes) else req.body
        return (f"{req.method} {req.url}\n{_pretty(body) if body else ''}\n\n"
                f"<- {response.status_code} ({response.elapsed.total_seconds() * 1000:.0f} ms)\n"
                f"{_pretty(response.text)}\n\n"
                f"повторить (с хоста — через http://localhost:8080):\n{as_curl(req)}")


def as_curl(req: requests.PreparedRequest) -> str:
    parts = ["curl", "-X", req.method, shlex.quote(req.url)]
    for name in ("Authorization", "Content-Type"):
        if name in req.headers:
            parts += ["-H", shlex.quote(f"{name}: {req.headers[name]}")]
    if req.body:
        body = req.body.decode() if isinstance(req.body, bytes) else req.body
        parts += ["--data-raw", shlex.quote(body)]
    return " ".join(parts)


def _pretty(text: str) -> str:
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except ValueError:
        return text
