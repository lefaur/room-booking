from behave import step

from framework import data, models
from framework.support import actor, expect, parse


@step('пользователь "{label}" создал этаж {width:d}x{height:d}')
def step_create_floor(context, label, width, height):
    resp = context.booking.create_floor(actor(context, label).access_token, name=data.unique_name("floor"),
                                        level=2, width=width, height=height)
    context.floor = parse(models.Floor, expect(resp, 201))


@step('пользователь "{label}" ставит переговорку "{res}" в точку {x:d},{y:d} размером {w:d}x{h:d}')
def step_place_room(context, label, res, x, y, w, h):
    context.resp = context.booking.create_resource(
        actor(context, label).access_token, floor_id=context.floor.id, kind="room",
        name=data.unique_name(res), capacity=6, x=x, y=y, w=w, h=h, equipment=["whiteboard"])
    if context.resp.status_code == 201:
        context.resources[res] = parse(models.Resource, context.resp)


@step('пользователь "{label}" поставил переговорку "{res}" в точку {x:d},{y:d} размером {w:d}x{h:d}')
def step_placed_room(context, label, res, x, y, w, h):
    step_place_room(context, label, res, x, y, w, h)
    expect(context.resp, 201)


@step('пользователь "{label}" меняет вместимость "{res}" на {capacity:d} с версией {version:d}')
def step_patch_with_version(context, label, res, capacity, version):
    context.resp = context.booking.patch_resource(actor(context, label).access_token, context.resources[res].id,
                                                  version=version, capacity=capacity)


@step('пользователь "{label}" изменил вместимость "{res}" на {capacity:d}')
def step_patched(context, label, res, capacity):
    step_patch_with_version(context, label, res, capacity, context.resources[res].version)
    updated = parse(models.Resource, expect(context.resp, 200))
    assert updated.version == context.resources[res].version + 1, "Версия не выросла"
    context.resources[res] = updated


@step('пользователь "{label}" открывает карту этажа на {day} {hhmm}')
def step_open_map(context, label, day, hhmm):
    at = data.office_datetime(day, hhmm, context.cfg.office_tz).isoformat()
    context.resp = context.booking.floor_map(actor(context, label).access_token, context.floor.id, at)


@step('на карте "{busy}" занята, "{free}" свободна')
def step_map_state(context, busy, free):
    floor_map = parse(models.FloorMap, context.resp)
    state = {r.id: r.busy for r in floor_map.resources}
    assert state[context.resources[busy].id] is True, f"{busy} должна быть занята"
    assert state[context.resources[free].id] is False, f"{free} должна быть свободна"
