from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="Minimum 8 characters")
    full_name: str = Field(..., min_length=1)
    role: str = Field(default="director", pattern="^(director|producer)$")


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserPublic(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    email_notifications: bool = True
    public_profile: bool = False
    currency: str = "USD"
    created_at: datetime

    model_config = {"from_attributes": True}


class UserSettingsUpdate(BaseModel):
    email_notifications: bool | None = None
    public_profile: bool | None = None
    currency: str | None = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic