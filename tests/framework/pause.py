"""Пауза перед уборкой: посмотреть руками на состояние, которое подготовил сценарий.

PAUSE=fail — останавливаться только на упавших сценариях, PAUSE=always — на каждом.
Сценарий ждёт, пока появится файл-флаг reports/continue (touch reports/continue на хосте),
или PAUSE_TIMEOUT минут: забытый прогон не держит стенд и блокировки вечно.
Выводится в терминал мимо перехвата behave, чтобы подсказка была видна и в параллельном прогоне.
"""
import os
import sys
import time
from pathlib import Path

MODE = os.getenv("PAUSE", "").lower()
TIMEOUT_MIN = float(os.getenv("PAUSE_TIMEOUT", "30"))
FLAG = Path(os.getenv("REPORTS_DIR", "/reports")) / "continue"
HOST_URL = os.getenv("PAUSE_HOST_URL", "http://localhost:8080")


def wanted(failed: bool) -> bool:
    return MODE in ("always", "1", "true") or (MODE == "fail" and failed)


def wait(scenario: str, failed: bool, users: dict, resources: dict) -> None:
    FLAG.unlink(missing_ok=True)  # флаг от прошлой паузы снял бы эту мгновенно
    lines = [
        "", "=" * 70,
        f"ПАУЗА {'(упал) ' if failed else ''}перед уборкой: {scenario}",
        f"Стенд: {HOST_URL}",
        *(f"  {label}: {u.email} / {u.password} ({u.role})" for label, u in users.items()),
        *(f"  ресурс {label}: {r.name} (id {r.id})" for label, r in resources.items()),
        f"Продолжить: touch reports/{FLAG.name}  (сам продолжит через {TIMEOUT_MIN:.0f} мин)",
        "=" * 70,
    ]
    print("\n".join(lines), file=sys.__stdout__, flush=True)
    deadline = time.monotonic() + TIMEOUT_MIN * 60
    while not FLAG.exists() and time.monotonic() < deadline:
        time.sleep(1)
    FLAG.unlink(missing_ok=True)
