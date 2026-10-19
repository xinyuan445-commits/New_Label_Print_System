"""Request/response schemas for /api/auth/*."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.types import LoginName


class LoginRequest(BaseModel):
    email: LoginName
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)
