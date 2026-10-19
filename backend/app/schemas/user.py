"""User-shaped schemas for responses + admin requests."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.user import PAGE_FEATURES, VISIBLE_PAGES, Role
from app.schemas.types import LoginName


class UserPublic(BaseModel):
    """User shape exposed to API consumers (no password hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: Role
    language: str
    is_active: bool
    must_change_password: bool
    created_at: datetime
    last_login_at: datetime | None
    permissions: dict[str, bool]
    visibility: dict[str, bool]


class CreateUserRequest(BaseModel):
    email: LoginName
    role: Role = Role.EDITOR
    language: str = Field(default="zh", min_length=2, max_length=8)
    temporary_password: str = Field(min_length=1, max_length=256)


class UpdateUserRequest(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    language: str | None = Field(default=None, min_length=2, max_length=8)
    permissions: dict[str, bool] | None = None
    visibility: dict[str, bool] | None = None

    @model_validator(mode="after")
    def check_permissions(self) -> UpdateUserRequest:
        if self.permissions is not None and any(
            key not in PAGE_FEATURES for key in self.permissions
        ):
            raise ValueError("unknown page permission")
        if self.visibility is not None and any(key not in VISIBLE_PAGES for key in self.visibility):
            raise ValueError("unknown visible page")
        return self


class ResetPasswordRequest(BaseModel):
    new_temporary_password: str = Field(min_length=1, max_length=256)


class CreateUserResponse(BaseModel):
    user: UserPublic
    temporary_password: str  # echoed back so admin can pass it to the user
