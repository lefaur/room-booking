"""Сервис scheduler: по расписанию дёргает внутренние джобы других сервисов.

SCHEDULER_MODE=auto — работает по расписанию; manual — только ручной запуск через API (так в автотестах,
чтобы время срабатывания определял тест, а не часы).
"""
import logging
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from common.security import SERVICE_TOKEN, Principal, require

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("scheduler")

ROOT_PATH = os.getenv("ROOT_PATH", "")
MODE = os.getenv("SCHEDULER_MODE", "auto")
OFFICE_TZ = os.getenv("OFFICE_TZ", "Europe/Moscow")
AUTH_URL = os.getenv("AUTH_INTERNAL_URL", "http://localhost:8001")
BOOKING_URL = os.getenv("BOOKING_INTERNAL_URL", "http://localhost:8002")


@dataclass
class Job:
    name: str
    url: str
    trigger: object
    schedule: str
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_run: dict | None = None


JOBS = {job.name: job for job in [
    Job("expire-pending", f"{BOOKING_URL}/internal/jobs/expire-pending", IntervalTrigger(minutes=1), "каждую минуту"),
    Job("send-reminders", f"{BOOKING_URL}/internal/jobs/send-reminders", IntervalTrigger(minutes=1), "каждую минуту"),
    Job("release-no-shows", f"{BOOKING_URL}/internal/jobs/release-no-shows", IntervalTrigger(minutes=1),
        "каждую минуту"),
    Job("sync-calendar", f"{BOOKING_URL}/internal/jobs/sync-calendar", CronTrigger(hour=3, timezone=OFFICE_TZ),
        "ежедневно в 03:00"),
    Job("cleanup-tokens", f"{AUTH_URL}/internal/jobs/cleanup-tokens", CronTrigger(hour=4, timezone=OFFICE_TZ),
        "ежедневно в 04:00"),
]}


MANUAL_WAIT_SECONDS = 30


def run_job(job: Job, trigger: str, wait: float = 0) -> dict:
    """Не больше одного запуска джобы одновременно. Запуск по расписанию при занятой джобе пропускается;
    ручной ждёт окончания текущего и выполняется заново: вызывающему важно, что джоба отработала
    уже после его изменений, а не что «какой-то запуск шёл»."""
    acquired = job.lock.acquire(timeout=wait) if wait else job.lock.acquire(blocking=False)
    if not acquired:
        return {"job": job.name, "status": "skipped", "detail": "Джоба уже выполняется"}
    started = datetime.now(timezone.utc)
    try:
        response = httpx.post(job.url, headers={"X-Service-Token": SERVICE_TOKEN}, timeout=60)
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if response.status_code == 200:
            status, result = "ok", body
        else:
            status, result = "failed", {"http_status": response.status_code, **body}
    except httpx.HTTPError as error:
        status, result = "failed", {"error": f"{type(error).__name__}: {error}"}
    finally:
        job.lock.release()
    job.last_run = {"job": job.name, "status": status, "trigger": trigger, "started_at": started,
                    "finished_at": datetime.now(timezone.utc), "result": result}
    log.info("джоба %s (%s): %s %s", job.name, trigger, status, result)
    return job.last_run


scheduler = BackgroundScheduler(timezone=OFFICE_TZ)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if MODE == "auto":
        for job in JOBS.values():
            scheduler.add_job(run_job, job.trigger, args=[job, "schedule"], id=job.name,
                              max_instances=1, coalesce=True)
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="OfficeSpace · scheduler", root_path=ROOT_PATH, lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "mode": MODE}


@app.get("/jobs")
def list_jobs(_: Principal = Depends(require("jobs.run"))):
    result = []
    for job in JOBS.values():
        planned = scheduler.get_job(job.name) if scheduler.running else None
        result.append({"name": job.name, "schedule": job.schedule, "mode": MODE,
                       "next_run_at": planned.next_run_time if planned else None, "last_run": job.last_run})
    return result


@app.post("/jobs/{name}/run")
def run_now(name: str, _: Principal = Depends(require("jobs.run"))):
    job = JOBS.get(name)
    if not job:
        raise HTTPException(404, f"Нет джобы {name}")
    run = run_job(job, "manual", wait=MANUAL_WAIT_SECONDS)
    if run["status"] == "skipped":
        raise HTTPException(409, run["detail"])
    return JSONResponse(jsonable(run), status_code=200 if run["status"] == "ok" else 502)


def jsonable(run: dict) -> dict:
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in run.items()}
