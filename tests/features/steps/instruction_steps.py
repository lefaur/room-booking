"""Шаги сценариев съёмки для инструкций пользователей (features/instructions, тег @instruction).

Сценарий съёмки — обычный UI-сценарий: готовит данные, проходит процесс в браузере теми же шагами,
что и автотесты, и на каждом экране инструкции делает снимок. Рядом со снимком пишется текст экрана
(.txt): надписи в инструкцию берутся дословно оттуда, а не из кода фронтенда.

Данные — как у живого офиса: переговорки с человеческими названиями, сотрудник с вымышленным именем,
а не «A-3f9c» и «Тест сотрудник». В обычный прогон сценарии не входят: sh run.sh -t @instruction.
"""
import logging
import os
import re
from pathlib import Path

from behave import step

from framework import models
from framework.prepare import floor_row, resource_row
from framework.support import actor, as_model, preparation

log = logging.getLogger("instruction")

# снимки — сразу в docs, если смонтирован (см. docs/user-guide/README.md), иначе в reports
IMG_DIR = Path(os.getenv("INSTR_DIR", "/reports/instructions"))
TEXT_DIR = Path(os.getenv("REPORTS_DIR", "/reports")) / "instructions-text"
FRAME = "outline: 4px solid #e53935 !important; outline-offset: 3px; border-radius: 4px;"
KINDS = {"переговорка": "room", "место": "desk"}
EQUIPMENT = {"проектор": "projector", "доска": "whiteboard", "телевизор": "tv", "видеосвязь": "videoconf"}


@step("есть этаж «{name}» с ресурсами")
def step_named_floor(context, name):
    """Этаж с настоящими названиями ресурсов; ярлык ресурса в сценарии — его название."""
    prep = preparation(context)
    assert prep, "Съёмка готовит данные только через БД (PREPARE_VIA=sql)"
    with prep:
        floor = floor_row(prep, name=name, level=3, width=800, height=480)
        rows = []
        for row in context.table:
            kind = KINDS[row["тип"]]
            x, y, w, h = (int(v) for v in row["x,y,w,h"].split(","))
            equipment = [EQUIPMENT[e.strip()] for e in row["оборудование"].split(",") if e.strip()]
            rows.append((row["название"], resource_row(
                prep, floor_id=lambda: floor["id"], kind=kind, name=row["название"],
                capacity=int(row["мест"]) if kind == "room" else 1, x=x, y=y, w=w, h=h, equipment=equipment)))
    context.floor = as_model(models.Floor, floor)
    for label, res in rows:
        context.resources[label] = as_model(models.Resource, res)


@step('сотрудника "{label}" зовут «{full_name}»')
def step_actor_name(context, label, full_name):
    """Имя в шапке сайта и в письмах — вымышленное, но человеческое."""
    person = actor(context, label, logged_in=False)
    context.db.execute("UPDATE auth.users SET full_name = %s WHERE id = %s", (full_name, person.id))


@step("снимок «{slug}» без рамки")
def step_snapshot(context, slug):
    _snapshot(context, slug, None)


@step("снимок «{slug}» с рамкой вокруг «{text}»")
def step_snapshot_text(context, slug, text):
    page = context.page
    target = page.get_by_text(text, exact=False).first
    if not target.count():
        target = page.get_by_role("button", name=text).first
    _snapshot(context, slug, target, text)


@step('снимок «{slug}» с рамкой вокруг ресурса "{label}"')
def step_snapshot_resource(context, slug, label):
    target = context.page.locator(f'[data-testid="map-resource"][data-name="{context.resources[label].name}"]')
    _snapshot(context, slug, target, label)


@step('снимок «{slug}» с рамкой вокруг элемента "{test_id}"')
def step_snapshot_test_id(context, slug, test_id):
    _snapshot(context, slug, context.page.get_by_test_id(test_id).first, test_id)


def _snapshot(context, slug: str, target, what: str | None = None) -> None:
    assert re.fullmatch(r"[a-z0-9-]+", slug), f"Имя снимка латиницей через дефис: {slug!r}"
    page = context.page
    page.wait_for_load_state("networkidle")
    framed = False
    if target is not None:
        try:
            target.wait_for(timeout=5000)
            target.evaluate("el => el.scrollIntoView({block: 'center'})")
            target.evaluate("(el, style) => { el.dataset.instrFrame = '1'; el.style.cssText += style; }", FRAME)
            framed = True
        except Exception:
            # снимок без рамки лучше, чем упавшая съёмка; такой кадр видно по WARNING в логе
            log.warning("Рамка: не нашли «%s» для снимка %s — снимок без рамки", what, slug)
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(IMG_DIR / f"{slug}.png"), animations="disabled")
    (TEXT_DIR / f"{slug}.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
    if framed:
        page.evaluate("""() => document.querySelectorAll('[data-instr-frame]').forEach(el => {
            el.style.outline = ''; el.style.outlineOffset = ''; delete el.dataset.instrFrame; })""")
    log.info("Снимок %s%s", slug, f" с рамкой вокруг «{what}»" if framed else "")

