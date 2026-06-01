# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.audit import AuditLog

from app.core.database import get_db
from app.core.security import hash_password, verify_password, encrypt_password
from app.api.deps import get_current_user, require_admin
from app.models.mailbox import Mailbox
from app.models.domain import Domain
from app.schemas.mailbox import (
    MailboxCreate,
    MailboxUpdate,
    MailboxResponse,
    MailboxQuotaUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/mailboxes", tags=["Mailboxes"])


def _mailbox_to_response(mb: Mailbox) -> MailboxResponse:
    quota_percent = 0.0
    if mb.quota_limit_mb and mb.quota_limit_mb > 0:
        quota_percent = round((mb.quota_used_mb or 0) / mb.quota_limit_mb * 100, 2)
    domain_name = None
    if mb.domain:
        domain_name = mb.domain.domain_name
    return MailboxResponse(
        id=mb.id,
        email=mb.email,
        domain_id=mb.domain_id,
        domain_name=domain_name,
        quota_limit_mb=mb.quota_limit_mb,
        quota_used_mb=mb.quota_used_mb or 0,
        quota_percent=quota_percent,
        is_active=mb.is_active,
        forward_to=mb.forward_to,
        auto_responder_enabled=mb.auto_responder_enabled,
        auto_responder_subject=mb.auto_responder_subject,
        auto_responder_body=mb.auto_responder_body,
        last_login=mb.last_login,
        created_at=mb.created_at,
    )


@router.get("/", response_model=List[MailboxResponse])
async def list_mailboxes(
    domain_id: Optional[int] = Query(None),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Mailbox).options(selectinload(Mailbox.domain)).offset(skip).limit(limit)
    if domain_id is not None:
        query = query.where(Mailbox.domain_id == domain_id)
    result = await db.execute(query)
    mailboxes = result.scalars().all()
    return [_mailbox_to_response(mb) for mb in mailboxes]


@router.post("/", response_model=MailboxResponse, status_code=status.HTTP_201_CREATED)
async def create_mailbox(
    data: MailboxCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    domain_result = await db.execute(select(Domain).where(Domain.id == data.domain_id))
    domain = domain_result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=400, detail="Domain not found")
    if domain.status != "active":
        raise HTTPException(status_code=400, detail="Domain is not active")

    existing = await db.execute(select(Mailbox).where(Mailbox.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Mailbox already exists")

    mailbox = Mailbox(
        email=data.email,
        domain_id=data.domain_id,
        password_hash=hash_password(data.password),
        password_encrypted=encrypt_password(data.password),
        quota_limit_mb=data.quota_limit_mb or 0,
        is_active=data.is_active if data.is_active is not None else True,
        forward_to=data.forward_to,
        created_at=datetime.now(timezone.utc),
    )
    db.add(mailbox)
    await db.flush()
    await db.refresh(mailbox)
    db.add(AuditLog(user_id=current_user.id, action="mailbox.create", resource_type="mailbox", resource_id=str(mailbox.id), details={"email": data.email}, created_at=datetime.now(timezone.utc)))
    await db.flush()
    return _mailbox_to_response(mailbox)


@router.get("/{mailbox_id}", response_model=MailboxResponse)
async def get_mailbox(
    mailbox_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Mailbox).options(selectinload(Mailbox.domain)).where(Mailbox.id == mailbox_id))
    mailbox = result.scalar_one_or_none()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    return _mailbox_to_response(mailbox)


@router.put("/{mailbox_id}", response_model=MailboxResponse)
async def update_mailbox(
    mailbox_id: int,
    data: MailboxUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Mailbox).options(selectinload(Mailbox.domain)).where(Mailbox.id == mailbox_id))
    mailbox = result.scalar_one_or_none()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")

    allowed = {"email", "is_active", "quota_limit_mb", "forward_to", "auto_responder_enabled", "auto_responder_subject", "auto_responder_body"}
    update_data = data.model_dump(exclude_unset=True)
    if "email" in update_data and update_data["email"] != mailbox.email:
        existing = await db.execute(select(Mailbox).where(Mailbox.email == update_data["email"]))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Mailbox with this email already exists")
    for field, value in update_data.items():
        if field in allowed:
            setattr(mailbox, field, value)
    db.add(mailbox)
    await db.flush()
    await db.refresh(mailbox)
    return _mailbox_to_response(mailbox)


@router.delete("/{mailbox_id}")
async def delete_mailbox(
    mailbox_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    result = await db.execute(select(Mailbox).where(Mailbox.id == mailbox_id))
    mailbox = result.scalar_one_or_none()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    db.add(AuditLog(user_id=current_user.id, action="mailbox.delete", resource_type="mailbox", resource_id=str(mailbox_id), details={"email": mailbox.email}, created_at=datetime.now(timezone.utc)))
    await db.delete(mailbox)
    await db.flush()
    return {"message": "Mailbox deleted successfully"}


@router.put("/{mailbox_id}/quota", response_model=MailboxResponse)
async def update_quota(
    mailbox_id: int,
    data: MailboxQuotaUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Mailbox).where(Mailbox.id == mailbox_id))
    mailbox = result.scalar_one_or_none()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    mailbox.quota_limit_mb = data.quota_limit_mb
    db.add(mailbox)
    await db.flush()
    await db.refresh(mailbox)
    return _mailbox_to_response(mailbox)


@router.put("/{mailbox_id}/password")
async def change_password(
    mailbox_id: int,
    body: Dict[str, str],
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    result = await db.execute(select(Mailbox).where(Mailbox.id == mailbox_id))
    mailbox = result.scalar_one_or_none()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    new_password = body.get("new_password")
    if not new_password:
        raise HTTPException(status_code=400, detail="new_password is required")
    mailbox.password_hash = hash_password(new_password)
    mailbox.password_encrypted = encrypt_password(new_password)
    db.add(mailbox)
    await db.flush()
    return {"message": "Password changed successfully"}


@router.put("/{mailbox_id}/forward")
async def set_forward(
    mailbox_id: int,
    body: Dict[str, Any],
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    result = await db.execute(select(Mailbox).where(Mailbox.id == mailbox_id))
    mailbox = result.scalar_one_or_none()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    forward_to = body.get("forward_to")
    mailbox.forward_to = forward_to
    db.add(mailbox)
    await db.flush()
    return {"message": "Forwarding updated"}


@router.put("/{mailbox_id}/autoresponder")
async def set_autoresponder(
    mailbox_id: int,
    enabled: bool,
    subject: str = "",
    body: str = "",
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    result = await db.execute(select(Mailbox).where(Mailbox.id == mailbox_id))
    mailbox = result.scalar_one_or_none()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    mailbox.auto_responder_enabled = enabled
    mailbox.auto_responder_subject = subject
    mailbox.auto_responder_body = body
    db.add(mailbox)
    await db.flush()
    return {"message": "Auto-responder updated"}
