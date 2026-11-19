"""Демо-этаж для того, кто открыл стенд руками: без него карта пустая, пока администратор не нарисует
этаж в редакторе. Создаётся при старте, если DEMO_DATA=1 и этажа с таким названием ещё нет.
Автотесты его не трогают: у них свои этажи с уникальными названиями."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from booking.models import Floor, Resource

FLOOR = dict(name="Офис, 3 этаж (демо)", level=3, width=1000, height=600)

ROOMS = [  # название, мест, оборудование, x
    ("Москва", 8, ["projector", "videoconf"], 30),
    ("Питер", 4, ["tv"], 270),
    ("Казань", 6, ["whiteboard"], 510),
    ("Новосибирск", 12, ["projector", "whiteboard", "videoconf"], 750),
]


def ensure_demo_floor(db: Session) -> None:
    if db.scalar(select(Floor).where(Floor.name == FLOOR["name"])):
        return
    floor = Floor(**FLOOR)
    db.add(floor)
    db.flush()
    for name, capacity, equipment, x in ROOMS:
        db.add(Resource(floor_id=floor.id, kind="room", name=name, capacity=capacity, equipment=equipment,
                        x=x, y=30, w=220, h=170))
    for i in range(10):  # два ряда по пять мест
        row, col = divmod(i, 5)
        db.add(Resource(floor_id=floor.id, kind="desk", name=f"Место {i + 1}", capacity=1, equipment=[],
                        x=100 + col * 170, y=320 + row * 130, w=120, h=80))
    db.commit()
