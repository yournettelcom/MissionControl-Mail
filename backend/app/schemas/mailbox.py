# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class MailboxCreate(BaseModel):
    email: EmailStr
    domain_id: int
    password: str = Field(..., min_length=8, max_length=255)
    quota_limit_mb: Optional[int] = 0
    is_active: Optional[bool] = True
    forward_to: Optional[str] = None


class MailboxUpdate(BaseModel):
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    quota_limit_mb: Optional[int] = None
    forward_to: Optional[str] = None
    auto_responder_enabled: Optional[bool] = None
    auto_responder_subject: Optional[str] = None
    auto_responder_body: Optional[str] = None


class MailboxResponse(BaseModel):
    id: int
    email: str
    domain_id: int
    domain_name: Optional[str] = None
    quota_limit_mb: int
    quota_used_mb: int
    quota_percent: float = 0.0
    is_active: bool
    forward_to: Optional[str] = None
    auto_responder_enabled: bool
    auto_responder_subject: Optional[str] = None
    auto_responder_body: Optional[str] = None
    last_login: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MailboxQuotaUpdate(BaseModel):
    quota_limit_mb: int = Field(..., ge=0)
