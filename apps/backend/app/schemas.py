from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Login(BaseModel):
    email: str
    password: str


class Profile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    org_id: str
    email: str
    role: str


class DocumentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    original_name: str
    declared_type: str
    detected_type: str | None
    status: str
    payment_status: str | None
    page_count: int
    extracted: dict
    evidence: list
    warnings: list
    error: str | None
    created_at: datetime
    updated_at: datetime


class Dashboard(BaseModel):
    total: int = 0
    finished: int = 0
    queued: int = 0
    accredited: int = 0
    review: int = 0
    errors: int = 0
