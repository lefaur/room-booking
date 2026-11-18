"""Блокировки общего состояния стенда между параллельными сценариями.

Общее состояние здесь — глобальные правила бронирования и производственный календарь. Сценарий, который
их меняет (@settings, @calendar), берёт блокировку монопольно; сценарий, который от них зависит, — совместно.
Пока правило изменено, ждут только зависимые сценарии, остальные (вход, токены, доставка событий) идут дальше.
Раньше такие сценарии шли отдельным последовательным проходом после параллельного.

Блокировки — flock на файлах в LOCK_DIR: все воркеры behavex работают в одном контейнере и видят одну папку.
Два прогона из разных контейнеров против одного стенда друг друга не видят — для этого нужен общий каталог.
"""
import logging
import os
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows без WSL: запуск одним процессом behave из IDE, соседей нет
    fcntl = None
    warnings.warn("fcntl недоступен: блокировки общего состояния выключены (только для запуска в один процесс)")

log = logging.getLogger("locks")

LOCK_DIR = Path(os.getenv("LOCK_DIR", "/tmp/officespace-locks"))
TIMEOUT = float(os.getenv("LOCK_TIMEOUT", "300"))
POLL = 0.02

# Реестр общего состояния. Берётся всегда в этом порядке: одинаковый порядок исключает взаимную блокировку
# (A держит календарь и ждёт правила, B держит правила и ждёт календарь). Имя совпадает с тегом сценария,
# который это состояние меняет.
SHARED_STATE = ("calendar", "settings")

# Сценарии с этими тегами не бронируют и не читают правила и календарь: блокировки им не нужны
INDEPENDENT_TAGS = {"auth", "messaging"}


class LockTimeout(AssertionError):
    pass


def plan(tags: set[str]) -> list[tuple[str, bool]]:
    """Какие блокировки нужны сценарию: [(имя, монопольно?)]."""
    if tags & INDEPENDENT_TAGS and not tags & ({"booking"} | set(SHARED_STATE)):
        return []
    return [(name, name in tags) for name in SHARED_STATE]


class ReadWriteLock:
    """Блокировка «читатели — писатель» на двух файлах.

    Сам ресурс — flock: совместный у читателей, монопольный у писателя. Перед ним турникет (gate):
    писатель занимает его на всё время ожидания, и новые читатели встают в очередь за ним. Без турникета
    при плотном потоке читателей ресурс никогда не освобождается полностью и писатель ждёт бесконечно.
    """

    def __init__(self, name: str):
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        self.name = name
        self._gate_path = LOCK_DIR / f"{name}.gate"
        self._res_path = LOCK_DIR / f"{name}.lock"
        self._res = None

    def acquire(self, exclusive: bool) -> float:
        """Возвращает, сколько секунд ждали."""
        started = time.monotonic()
        deadline = started + TIMEOUT
        res = open(self._res_path, "a")
        try:
            with open(self._gate_path, "a") as gate:
                self._flock(gate, fcntl.LOCK_EX, deadline)
                # турникет отпускается при закрытии файла, как только ресурс получен
                self._flock(res, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH, deadline)
        except BaseException:
            res.close()
            raise
        self._res = res
        return time.monotonic() - started

    def release(self) -> None:
        if self._res is not None:
            self._res.close()  # закрытие файла снимает flock
            self._res = None

    def _flock(self, file, mode: int, deadline: float) -> None:
        while True:
            try:
                fcntl.flock(file, mode | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise LockTimeout(f"Блокировка «{self.name}» не получена за {TIMEOUT:.0f} с: "
                                      f"какой-то сценарий держит её слишком долго") from None
                time.sleep(POLL)


@dataclass
class ScenarioLocks:
    """Блокировки одного сценария: берутся до первого шага, снимаются после отката его изменений."""
    held: list[ReadWriteLock] = field(default_factory=list)

    def acquire(self, tags: set[str]) -> list[str]:
        """Возвращает строки для журнала хуков: что взяли и сколько ждали."""
        if fcntl is None:
            return ["блокировки выключены: нет fcntl"]
        notes = []
        for name, exclusive in plan(tags):
            lock = ReadWriteLock(name)
            waited = lock.acquire(exclusive)
            self.held.append(lock)
            notes.append(f"блокировка «{name}» {'монопольно' if exclusive else 'совместно'}, ждали {waited:.2f} с")
            log.info(notes[-1])
        return notes or ["блокировки не нужны"]

    def release(self) -> None:
        for lock in reversed(self.held):
            lock.release()
        self.held.clear()
