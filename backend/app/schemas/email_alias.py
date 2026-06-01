# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class EmailAliasCreate(BaseModel):
    source_email: str = Field(..., min_length=1, max_length=255)
    domain_id: int
    destinations: str = Field(..., min_length=1, comment="Comma-separated destination emails")
    description: Optional[str] = None
    is_active: Optional[bool] = True


class EmailAliasUpdate(BaseModel):
    source_email: Optional[str] = Field(None, min_length=1, max_length=255)
    destinations: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class EmailAliasResponse(BaseModel):
    id: int
    source_email: str
    domain_id: int
    domain_name: Optional[str] = None
    destinations: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
