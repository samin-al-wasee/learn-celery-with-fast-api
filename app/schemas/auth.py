from pydantic import BaseModel, EmailStr, Field

from app.models import UserRole


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=150)
    role: UserRole
    specialty: str | None = Field(default=None, max_length=100)


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