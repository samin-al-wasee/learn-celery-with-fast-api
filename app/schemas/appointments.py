from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import AppointmentStatus


class AppointmentCreate(BaseModel):
    """Exactly one of doctor_id (patient books) / patient_id (doctor books)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    doctor_id: int | None = None
    patient_id: int | None = None
    scheduled_at: datetime
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def _validate_participants(self) -> "AppointmentCreate":
        if (self.doctor_id is None) == (self.patient_id is None):
            raise ValueError("exactly one of doctor_id (as patient) or patient_id (as doctor) is required")
        return self


class AppointmentUpdate(BaseModel):
    """PATCH semantics: only sent fields are applied; status accepts only
    \"confirmed\" (cancellation is its own idempotent endpoint)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    status: Literal[AppointmentStatus.CONFIRMED] | None = None
    scheduled_at: datetime | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=500)


class UserBrief(BaseModel):
    id: int
    full_name: str
    role: str


class AppointmentResponse(BaseModel):
    id: int
    patient: UserBrief
    doctor: UserBrief
    scheduled_at: datetime
    status: AppointmentStatus
    reason: str | None