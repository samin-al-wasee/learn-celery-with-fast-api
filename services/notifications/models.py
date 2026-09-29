from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from services.notifications.db import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_id_id", "user_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # M6: a plain id copied from the event, not a foreign key: the users table belongs to the
    # monolith, and a FK would tie this service to its locks, migrations and uptime.
    user_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(50))
    body: Mapped[str] = mapped_column(String(300))
    appointment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcessedEvent(Base):
    """Inbox: one row per event this service has fully applied."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    consumer: Mapped[str] = mapped_column(String(50))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
