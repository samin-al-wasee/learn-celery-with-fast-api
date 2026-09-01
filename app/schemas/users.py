from pydantic import BaseModel, EmailStr, Field

from app.models import UserRole

PHONE_PATTERN = r"^\+[1-9]\d{1,14}$"


class ProfileUpdate(BaseModel):
    """PATCH semantics: only sent fields are applied; null clears optional fields."""

    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    specialty: str | None = Field(default=None, min_length=2, max_length=100)
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)


class ProfileResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    specialty: str | None
    phone: str | None