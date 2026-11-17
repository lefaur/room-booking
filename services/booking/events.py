from datetime import timedelta

from booking.db import Base, SessionLocal
from booking.models import Booking, Resource
from common.messaging import Outbox

outbox = Outbox(Base, SessionLocal, source="booking")


def booking_payload(booking: Booking, resource: Resource, **extra) -> dict:
    return {
        "booking_id": booking.id, "user_id": booking.user_id, "user_email": booking.user_email,
        "resource_id": resource.id, "resource_name": resource.name, "resource_kind": resource.kind,
        "start": booking.start_at.isoformat(), "end": booking.end_at.isoformat(), "status": booking.status,
        **extra,
    }


def emit(db, event_type: str, booking: Booking, **extra) -> None:
    resource = db.get(Resource, booking.resource_id)
    outbox.add(db, event_type, booking_payload(booking, resource, **extra))


def confirm_deadline(booking: Booking, timeout_minutes: int) -> str:
    return (booking.created_at + timedelta(minutes=timeout_minutes)).isoformat()
