# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.contact import Task
from app.models.mailbox import Mailbox
from app.core.database import get_db
from app.api.deps import get_current_user
from app.services.imap_service import ImapService
from app.services.sieve_service import SieveService
from app.api.webmail import notify_user
from app.core.security import decrypt_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/email", tags=["Email Features"])


# ─── Sieve Filters ─────────────────────────────────────────────────

@router.get("/filters")
async def list_filters(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Mailbox).where(Mailbox.email == current_user.email))
    mb = result.scalar_one_or_none()
    if not mb:
        raise HTTPException(400, "No mailbox configured for this user")
    svc = SieveService()
    return await svc.list_filters(current_user.email)


@router.put("/filters")
async def save_filters(
    filters: List[Dict[str, Any]] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Mailbox).where(Mailbox.email == current_user.email))
    mb = result.scalar_one_or_none()
    if not mb:
        raise HTTPException(400, "No mailbox configured for this user")
    svc = SieveService()
    ok = await svc.save_filters(current_user.email, filters)
    if not ok:
        raise HTTPException(500, "Failed to save filters")
    return {"message": "Filters saved", "count": len(filters)}


@router.get("/filters/script")
async def get_sieve_script(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Mailbox).where(Mailbox.email == current_user.email))
    mb = result.scalar_one_or_none()
    if not mb:
        raise HTTPException(400, "No mailbox configured")
    svc = SieveService()
    return {"script": await svc.get_script(current_user.email)}


# ─── Email Templates ───────────────────────────────────────────────

@router.get("/templates")
async def list_templates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.email_feature import EmailTemplate
    result = await db.execute(
        select(EmailTemplate).where(EmailTemplate.user_id == current_user.id).order_by(EmailTemplate.created_at.desc())
    )
    return result.scalars().all()


@router.post("/templates")
async def create_template(
    data: Dict[str, str] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.email_feature import EmailTemplate
    tpl = EmailTemplate(
        user_id=current_user.id,
        name=data.get("name", "Sem nome"),
        subject=data.get("subject", ""),
        body=data.get("body", ""),
    )
    db.add(tpl)
    await db.flush()
    return {"id": tpl.id, "name": tpl.name, "subject": tpl.subject, "body": tpl.body, "created_at": tpl.created_at.isoformat()}


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.email_feature import EmailTemplate
    result = await db.execute(
        select(EmailTemplate).where(EmailTemplate.id == template_id, EmailTemplate.user_id == current_user.id)
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(404, "Template not found")
    await db.delete(tpl)
    await db.flush()
    return {"message": "Template deleted"}


# ─── Undo Send ─────────────────────────────────────────────────────

@router.post("/undo-send/schedule")
async def schedule_undo(
    data: Dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.email_feature import UndoSend
    msg_id = data.get("message_id", f"undo_{datetime.now(timezone.utc).timestamp()}")
    delay = data.get("delay_seconds", 30)
    entry = UndoSend(
        user_id=current_user.id,
        message_id=msg_id,
        to_addrs=data.get("to", []),
        cc_addrs=data.get("cc", []),
        bcc_addrs=data.get("bcc", []),
        subject=data.get("subject", ""),
        body_text=data.get("body_text", ""),
        body_html=data.get("body_html"),
        scheduled_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=delay),
        status="pending",
    )
    db.add(entry)
    await db.flush()
    return {"message_id": msg_id, "undo_by": entry.expires_at.isoformat()}


@router.post("/undo-send/{message_id}")
async def undo_send(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.email_feature import UndoSend
    result = await db.execute(
        select(UndoSend).where(UndoSend.message_id == message_id, UndoSend.user_id == current_user.id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Message not found or undo window expired")
    if entry.status != "pending":
        raise HTTPException(400, "Undo window expired")
    entry.status = "cancelled"
    db.add(entry)
    await db.flush()
    return {"message": "Send undone successfully"}


# ─── Snooze ─────────────────────────────────────────────────────────

@router.post("/snooze")
async def snooze_message(
    data: Dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.email_feature import SnoozedMessage
    import json
    snooze_until = data.get("snooze_until")
    if isinstance(snooze_until, str):
        snooze_until = datetime.fromisoformat(snooze_until)
    snoozed = SnoozedMessage(
        user_id=current_user.id,
        message_uid=str(data.get("message_uid", "")),
        mailbox=data.get("mailbox", "INBOX"),
        snooze_until=snooze_until or datetime.now(timezone.utc),
    )
    db.add(snoozed)
    await db.flush()
    return {
        "id": snoozed.id,
        "message_uid": snoozed.message_uid,
        "mailbox": snoozed.mailbox,
        "snooze_until": snoozed.snooze_until.isoformat(),
        "created_at": snoozed.created_at.isoformat(),
    }


@router.get("/snooze")
async def list_snoozed(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.email_feature import SnoozedMessage
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(SnoozedMessage).where(
            SnoozedMessage.user_id == current_user.id,
            SnoozedMessage.snooze_until > now,
        )
    )
    return [
        {
            "id": s.id,
            "message_uid": s.message_uid,
            "mailbox": s.mailbox,
            "snooze_until": s.snooze_until.isoformat(),
            "created_at": s.created_at.isoformat(),
        }
        for s in result.scalars()
    ]


# ─── Search ─────────────────────────────────────────────────────────

@router.get("/search")
async def search_emails(
    q: str = Query(..., min_length=1),
    mailbox: str = Query("INBOX"),
    limit: int = Query(50, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Mailbox).where(Mailbox.email == current_user.email))
    mb = result.scalar_one_or_none()
    if not mb:
        raise HTTPException(400, "No mailbox configured")
    svc = ImapService()
    pw = decrypt_password(mb.password_encrypted) if mb.password_encrypted else mb.password_hash
    data = await svc.fetch_emails(current_user.email, pw, mailbox=mailbox, limit=200)
    filtered = [
        m for m in data.get("messages", [])
        if q.lower() in m.get("subject", "").lower()
        or q.lower() in m.get("from", "").lower()
        or q.lower() in m.get("to", "").lower()
    ]
    return {"messages": filtered[:limit], "total": len(filtered), "query": q}
