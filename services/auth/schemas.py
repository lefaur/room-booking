import re
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def _strong_password(value: str) -> str:
    if not re.search(r"[A-Za-zА-Яа-я]", value) or not re.search(r"\d", value):
        raise ValueError("Пароль должен содержать буквы и цифры")
    return value


StrongPassword = Annotated[str, Field(min_length=8, max_length=128), AfterValidator(_strong_password)]


class RegisterIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=120)
    password: StrongPassword
    full_name: str = Field(min_length=1, max_length=120)


class ForgotPasswordIn(BaseModel):
    email: str


class ResetPasswordIn(BaseModel):
    token: str
    new_password: StrongPassword


class LoginIn(BaseModel):
    email: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    is_active: bool | None = None


class RoleOut(BaseModel):
    name: str
    title: str
    permissions: list[str]
