from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.appointments import UserBrief


class RecordCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    patient_id: int
    title: str = Field(min_length=1, max_length=200)
    notes: str = Field(min_length=1, max_length=5000)


class RecordUpdate(BaseModel):
    # PATCH semantics: only the fields the client actually sent are applied.
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, min_length=1, max_length=5000)


class RecordResponse(BaseModel):
    id: int
    title: str
    notes: str
    patient: UserBrief
    doctor: UserBrief
    created_at: datetime