from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from .models import UserRole


class UserRegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8)


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    public_id: str
    full_name: str
    email: str
    role: UserRole
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ContactMessageRequest(BaseModel):
    message: str = Field(..., min_length=3, max_length=2000)


class AdminUserRow(BaseModel):
    public_id: str
    email: str
    full_name: str
    created_at: datetime

    class Config:
        from_attributes = True
