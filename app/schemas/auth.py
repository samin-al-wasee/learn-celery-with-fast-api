from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models import UserRole


class SignupRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=150)
    role: UserRole
    specialty: str | None = Field(default=None, min_length=2, max_length=100)

    @model_validator(mode="after")
    def _doctor_requires_specialty(self) -> "SignupRequest":
        # Role-specific shape rule: a doctor without a specialty pollutes the
        # directory. Schema-level: it's static, not time-dependent.
        if self.role == UserRole.DOCTOR and not self.specialty:
            raise ValueError("specialty is required for doctors")
        return self


class SignupResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"