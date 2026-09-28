from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

PAYMENT_PROCESSING = "processing"
PAYMENT_PAID = "paid"
PAYMENT_DECLINED = "declined"


class Payment(Base):
    """Deposit saga state: one row per appointment, advanced by the collect_deposit task."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True)
    # M6: a plain string, not a Postgres enum: new saga states shouldn't need ALTER TYPE.
    status: Mapped[str] = mapped_column(String(20), default=PAYMENT_PROCESSING)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    charge_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
