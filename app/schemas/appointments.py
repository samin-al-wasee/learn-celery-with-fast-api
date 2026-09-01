from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models import AppointmentStatus


class AppointmentCreate(BaseModel):
    """Exactly one of doctor_id (patient books) / patient_id (doctor books)."""

    doctor_id: int | None = None
    patient_id: int | None = None
    scheduled_at: datetime
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validate_participants(self) -> "AppointmentCreate":
        if (self.doctor_id is None) == (self.patient_id is None):
            raise ValueError("exactly one of doctor_id (as patient) or patient_id (as doctor) is required")
        return self


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