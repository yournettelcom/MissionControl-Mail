# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field


class ContactGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    color: Optional[str] = "#3B82F6"


class ContactGroupUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class ContactGroupResponse(BaseModel):
    id: int
    name: str
    color: str
    contact_count: int = 0
    created_at: datetime
    model_config = {"from_attributes": True}


class ContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., max_length=255)
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    notes: Optional[str] = None
    group_id: Optional[int] = None
    is_favorite: Optional[bool] = False
    metadata: Optional[dict[str, Any]] = None


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    notes: Optional[str] = None
    group_id: Optional[int] = None
    is_favorite: Optional[bool] = None
    metadata: Optional[dict[str, Any]] = None


class ContactResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    notes: Optional[str] = None
    group_id: Optional[int] = None
    group_name: Optional[str] = None
    is_favorite: bool
    photo_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class CalendarCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    color: Optional[str] = "#3B82F6"
    is_default: Optional[bool] = False


class CalendarUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    is_default: Optional[bool] = None


class CalendarResponse(BaseModel):
    id: int
    name: str
    color: str
    is_default: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class CalendarEventCreate(BaseModel):
    calendar_id: int
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    location: Optional[str] = None
    all_day: Optional[bool] = False
    start_time: datetime
    end_time: datetime
    timezone: Optional[str] = "UTC"
    recurrence_rule: Optional[str] = None
    color: Optional[str] = None


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    all_day: Optional[bool] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    timezone: Optional[str] = None
    recurrence_rule: Optional[str] = None
    color: Optional[str] = None
    is_cancelled: Optional[bool] = None


class CalendarEventResponse(BaseModel):
    id: int
    calendar_id: int
    calendar_name: Optional[str] = None
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    all_day: bool
    start_time: datetime
    end_time: datetime
    timezone: str
    recurrence_rule: Optional[str] = None
    color: Optional[str] = None
    is_cancelled: bool
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    priority: Optional[int] = 0
    color: Optional[str] = None
    calendar_id: Optional[int] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: Optional[bool] = None
    priority: Optional[int] = None
    color: Optional[str] = None
    calendar_id: Optional[int] = None


class TaskResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: bool
    completed_at: Optional[datetime] = None
    priority: int
    color: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
