# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import logging
import os
import aiofiles
from datetime import datetime, timezone
from typing import List, Dict, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, delete, case

from app.models.user import User
from app.models.contact import Contact, ContactGroup, Calendar, CalendarEvent, Task
from app.core.database import get_db
from app.api.deps import get_current_user
from app.schemas.contact import (
    ContactGroupCreate, ContactGroupUpdate, ContactGroupResponse,
    ContactCreate, ContactUpdate, ContactResponse,
    CalendarCreate, CalendarUpdate, CalendarResponse,
    CalendarEventCreate, CalendarEventUpdate, CalendarEventResponse,
    TaskCreate, TaskUpdate, TaskResponse,
)

PHOTO_DIR = "/opt/missioncontrol/contact_photos"
MAX_PHOTO_SIZE = 2 * 1024 * 1024

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["PIM"])


# ─── Contact Groups ────────────────────────────────────────────────

@router.get("/contact-groups", response_model=List[ContactGroupResponse])
async def list_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ContactGroup).where(ContactGroup.user_id == current_user.id).order_by(ContactGroup.name)
    )
    groups = result.scalars().all()
    responses = []
    for g in groups:
        cnt = await db.scalar(select(func.count(Contact.id)).where(Contact.group_id == g.id))
        r = ContactGroupResponse.model_validate(g)
        r.contact_count = cnt or 0
        responses.append(r)
    return responses


@router.post("/contact-groups", response_model=ContactGroupResponse, status_code=201)
async def create_group(
    data: ContactGroupCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    group = ContactGroup(user_id=current_user.id, name=data.name, color=data.color or "#3B82F6")
    db.add(group)
    await db.flush()
    await db.refresh(group)
    return ContactGroupResponse.model_validate(group)


@router.put("/contact-groups/{group_id}", response_model=ContactGroupResponse)
async def update_group(
    group_id: int,
    data: ContactGroupUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ContactGroup).where(ContactGroup.id == group_id, ContactGroup.user_id == current_user.id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(404, "Group not found")
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(group, field, val)
    db.add(group)
    await db.flush()
    await db.refresh(group)
    return ContactGroupResponse.model_validate(group)


@router.delete("/contact-groups/{group_id}")
async def delete_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ContactGroup).where(ContactGroup.id == group_id, ContactGroup.user_id == current_user.id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(404, "Group not found")
    await db.execute(delete(Contact).where(Contact.group_id == group_id))
    await db.delete(group)
    await db.flush()
    return {"message": "Group deleted"}


# ─── Contacts ──────────────────────────────────────────────────────

@router.get("/contacts", response_model=List[ContactResponse])
async def list_contacts(
    search: str = Query(None),
    group_id: int = Query(None),
    favorite: bool = Query(None),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Contact).where(Contact.user_id == current_user.id)
    if search:
        q = f"%{search}%"
        query = query.where(or_(Contact.name.ilike(q), Contact.email.ilike(q), Contact.company.ilike(q)))
    if group_id is not None:
        query = query.where(Contact.group_id == group_id)
    if favorite is not None:
        query = query.where(Contact.is_favorite == favorite)
    query = query.order_by(Contact.name).offset(skip).limit(limit)
    result = await db.execute(query)
    contacts = result.scalars().all()
    responses = []
    for c in contacts:
        r = ContactResponse.model_validate(c)
        if c.group_id:
            grp = await db.get(ContactGroup, c.group_id)
            r.group_name = grp.name if grp else None
        responses.append(r)
    return responses


@router.get("/contacts/{contact_id}", response_model=ContactResponse)
async def get_contact(
    contact_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Contact).where(Contact.id == contact_id, Contact.user_id == current_user.id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(404, "Contact not found")
    r = ContactResponse.model_validate(contact)
    if contact.group_id:
        grp = await db.get(ContactGroup, contact.group_id)
        r.group_name = grp.name if grp else None
    return r


@router.post("/contacts", response_model=ContactResponse, status_code=201)
async def create_contact(
    data: ContactCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    contact = Contact(user_id=current_user.id, **data.model_dump())
    db.add(contact)
    await db.flush()
    await db.refresh(contact)
    r = ContactResponse.model_validate(contact)
    if contact.group_id:
        grp = await db.get(ContactGroup, contact.group_id)
        r.group_name = grp.name if grp else None
    return r


@router.put("/contacts/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: int,
    data: ContactUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Contact).where(Contact.id == contact_id, Contact.user_id == current_user.id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(404, "Contact not found")
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(contact, field, val)
    contact.updated_at = datetime.now(timezone.utc)
    db.add(contact)
    await db.flush()
    await db.refresh(contact)
    r = ContactResponse.model_validate(contact)
    if contact.group_id:
        grp = await db.get(ContactGroup, contact.group_id)
        r.group_name = grp.name if grp else None
    return r


@router.delete("/contacts/{contact_id}")
async def delete_contact(
    contact_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Contact).where(Contact.id == contact_id, Contact.user_id == current_user.id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(404, "Contact not found")
    await db.delete(contact)
    await db.flush()
    return {"message": "Contact deleted"}


@router.post("/contacts/{contact_id}/photo")
async def upload_contact_photo(
    contact_id: int,
    photo: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Contact).where(Contact.id == contact_id, Contact.user_id == current_user.id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(404, "Contact not found")
    if not photo.content_type or not photo.content_type.startswith("image/"):
        raise HTTPException(400, "Only image files are allowed")
    body = await photo.read()
    if len(body) > MAX_PHOTO_SIZE:
        raise HTTPException(400, f"Photo must be under {MAX_PHOTO_SIZE // (1024*1024)}MB")
    os.makedirs(PHOTO_DIR, exist_ok=True)
    ext = os.path.splitext(photo.filename or "photo.jpg")[1] or ".jpg"
    filename = f"contact_{contact_id}_{uuid4().hex}{ext}"
    filepath = os.path.join(PHOTO_DIR, filename)
    async with aiofiles.open(filepath, "wb") as f:
        await f.write(body)
    contact.photo_url = f"/contact_photos/{filename}"
    contact.updated_at = datetime.now(timezone.utc)
    db.add(contact)
    await db.flush()
    return {"photo_url": contact.photo_url, "message": "Photo uploaded"}


# ─── Calendars ─────────────────────────────────────────────────────

@router.get("/calendars", response_model=List[CalendarResponse])
async def list_calendars(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Calendar).where(Calendar.user_id == current_user.id).order_by(Calendar.name)
    )
    return [CalendarResponse.model_validate(c) for c in result.scalars().all()]


@router.post("/calendars", response_model=CalendarResponse, status_code=201)
async def create_calendar(
    data: CalendarCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cal = Calendar(user_id=current_user.id, name=data.name, color=data.color or "#3B82F6", is_default=data.is_default or False)
    db.add(cal)
    await db.flush()
    await db.refresh(cal)
    return CalendarResponse.model_validate(cal)


@router.put("/calendars/{calendar_id}", response_model=CalendarResponse)
async def update_calendar(
    calendar_id: int,
    data: CalendarUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Calendar).where(Calendar.id == calendar_id, Calendar.user_id == current_user.id))
    cal = result.scalar_one_or_none()
    if not cal:
        raise HTTPException(404, "Calendar not found")
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(cal, field, val)
    db.add(cal)
    await db.flush()
    await db.refresh(cal)
    return CalendarResponse.model_validate(cal)


@router.delete("/calendars/{calendar_id}")
async def delete_calendar(
    calendar_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Calendar).where(Calendar.id == calendar_id, Calendar.user_id == current_user.id))
    cal = result.scalar_one_or_none()
    if not cal:
        raise HTTPException(404, "Calendar not found")
    await db.execute(delete(CalendarEvent).where(CalendarEvent.calendar_id == calendar_id))
    await db.delete(cal)
    await db.flush()
    return {"message": "Calendar deleted"}


# ─── Events ─────────────────────────────────────────────────────────

@router.get("/events", response_model=List[CalendarEventResponse])
async def list_events(
    start: str = Query(None, description="ISO date filter start"),
    end: str = Query(None, description="ISO date filter end"),
    calendar_id: int = Query(None),
    skip: int = 0,
    limit: int = 200,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(CalendarEvent).where(CalendarEvent.user_id == current_user.id)
    if calendar_id is not None:
        query = query.where(CalendarEvent.calendar_id == calendar_id)
    if start:
        query = query.where(CalendarEvent.end_time >= start)
    if end:
        query = query.where(CalendarEvent.start_time <= end)
    query = query.order_by(CalendarEvent.start_time).offset(skip).limit(limit)
    result = await db.execute(query)
    events = result.scalars().all()
    responses = []
    for e in events:
        r = CalendarEventResponse.model_validate(e)
        cal = await db.get(Calendar, e.calendar_id)
        r.calendar_name = cal.name if cal else None
        responses.append(r)
    return responses


@router.post("/events", response_model=CalendarEventResponse, status_code=201)
async def create_event(
    data: CalendarEventCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cal = await db.get(Calendar, data.calendar_id)
    if not cal or cal.user_id != current_user.id:
        raise HTTPException(400, "Calendar not found")
    event = CalendarEvent(user_id=current_user.id, **data.model_dump())
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return CalendarEventResponse.model_validate(event)


@router.put("/events/{event_id}", response_model=CalendarEventResponse)
async def update_event(
    event_id: int,
    data: CalendarEventUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id, CalendarEvent.user_id == current_user.id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(404, "Event not found")
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(event, field, val)
    event.updated_at = datetime.now(timezone.utc)
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return CalendarEventResponse.model_validate(event)


@router.delete("/events/{event_id}")
async def delete_event(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id, CalendarEvent.user_id == current_user.id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(404, "Event not found")
    await db.delete(event)
    await db.flush()
    return {"message": "Event deleted"}


# ─── Tasks ──────────────────────────────────────────────────────────

@router.get("/tasks", response_model=List[TaskResponse])
async def list_tasks(
    completed: bool = Query(None),
    priority: int = Query(None),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Task).where(Task.user_id == current_user.id)
    if completed is not None:
        query = query.where(Task.completed == completed)
    if priority is not None:
        query = query.where(Task.priority == priority)
    query = query.order_by(case((Task.due_date.is_(None), 1), else_=0), Task.due_date.asc(), Task.priority.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return [TaskResponse.model_validate(t) for t in result.scalars().all()]


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = Task(user_id=current_user.id, **data.model_dump())
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return TaskResponse.model_validate(task)


@router.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int,
    data: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Task).where(Task.id == task_id, Task.user_id == current_user.id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    update_data = data.model_dump(exclude_unset=True)
    if "completed" in update_data and update_data["completed"] and not task.completed:
        task.completed_at = datetime.now(timezone.utc)
    elif "completed" in update_data and not update_data["completed"]:
        task.completed_at = None
    for field, val in update_data.items():
        if field != "completed":
            setattr(task, field, val)
    task.updated_at = datetime.now(timezone.utc)
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return TaskResponse.model_validate(task)


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Task).where(Task.id == task_id, Task.user_id == current_user.id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    await db.delete(task)
    await db.flush()
    return {"message": "Task deleted"}
