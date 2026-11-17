from auth.db import Base, SessionLocal
from common.messaging import Outbox

outbox = Outbox(Base, SessionLocal, source="auth")
