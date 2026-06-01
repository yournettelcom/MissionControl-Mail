# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.mailbox import Mailbox
from app.core.database import get_db
from app.api.deps import get_current_user
from app.core.security import verify_token, decrypt_password
from app.services.imap_service import ImapService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/mail", tags=["Webmail"])


def _get_mailbox_creds(user: User, db: AsyncSession) -> tuple[str, str]:
    if "@" in user.email:
        return user.email, ""
    return "", ""


@router.get("/mailboxes")
async def list_mailboxes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Mailbox).where(Mailbox.email == current_user.email))
    mailbox = result.scalar_one_or_none()
    if not mailbox:
        raise HTTPException(400, "No email mailbox configured for this user")
    svc = ImapService()
    pw = decrypt_password(mailbox.password_encrypted) if mailbox.password_encrypted else mailbox.password_hash
    return await svc.fetch_mailboxes(current_user.email, pw)


@router.get("/messages")
async def list_messages(
    mailbox: str = Query("INBOX"),
    limit: int = Query(50, le=200),
    page: int = Query(1, ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Mailbox).where(Mailbox.email == current_user.email))
    mb = result.scalar_one_or_none()
    if not mb:
        raise HTTPException(400, "No email mailbox configured")
    pw = decrypt_password(mb.password_encrypted) if mb.password_encrypted else mb.password_hash
    svc = ImapService()
    return await svc.fetch_emails(
        current_user.email, pw,
        mailbox=mailbox, limit=limit, offset=(page - 1) * limit,
    )


@router.get("/messages/{uid}")
async def get_message(
    uid: str,
    mailbox: str = Query("INBOX"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Mailbox).where(Mailbox.email == current_user.email))
    mb = result.scalar_one_or_none()
    if not mb:
        raise HTTPException(400, "No email mailbox configured")
    pw = decrypt_password(mb.password_encrypted) if mb.password_encrypted else mb.password_hash
    svc = ImapService()
    return await svc.fetch_email_body(current_user.email, pw, uid, mailbox)


@router.post("/send")
async def send_email(
    data: Dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Mailbox).where(Mailbox.email == current_user.email))
    mb = result.scalar_one_or_none()
    if not mb:
        raise HTTPException(400, "No email mailbox configured")
    pw = decrypt_password(mb.password_encrypted) if mb.password_encrypted else mb.password_hash
    svc = ImapService()
    ok = await svc.send_email(
        username=current_user.email,
        password=pw,
        to=data.get("to", []),
        subject=data.get("subject", ""),
        body_text=data.get("body_text", ""),
        body_html=data.get("body_html"),
        cc=data.get("cc"),
        bcc=data.get("bcc"),
        in_reply_to=data.get("in_reply_to"),
        references=data.get("references"),
    )
    if not ok:
        raise HTTPException(500, "Failed to send email")
    return {"message": "Email sent successfully", "id": data.get("in_reply_to", "")}


@router.post("/draft")
async def save_draft(
    data: Dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Mailbox).where(Mailbox.email == current_user.email))
    mb = result.scalar_one_or_none()
    if not mb:
        raise HTTPException(400, "No mailbox configured")
    pw = decrypt_password(mb.password_encrypted) if mb.password_encrypted else mb.password_hash
    svc = ImapService()
    ok = await svc.save_draft(
        current_user.email,
        pw,
        to_list=data.get("to", []),
        cc_list=data.get("cc", []),
        subject=data.get("subject", ""),
        body_text=data.get("body_text", ""),
        body_html=data.get("body_html"),
    )
    if not ok:
        raise HTTPException(500, "Failed to save draft")
    return {
        "message": "Draft saved",
        "id": data.get("id", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── WebSocket push notifications ──────────────────────────────────

connected_clients: dict[int, list[WebSocket]] = {}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    user_id: Optional[int] = None
    authenticated = False
    try:
        data = await websocket.receive_json()
        token = data.get("token", "")
        payload = verify_token(token)
        if payload is None:
            await websocket.send_json({"type": "error", "message": "Invalid or expired token"})
            await websocket.close(4001, "Authentication failed")
            return
        user_id = int(payload.get("sub", 0))
        if not user_id:
            await websocket.close(4000, "Invalid user")
            return
        authenticated = True
        if user_id not in connected_clients:
            connected_clients[user_id] = []
        connected_clients[user_id].append(websocket)
        await websocket.send_json({"type": "connected", "message": "Push notifications active"})
        while True:
            try:
                msg = await websocket.receive_json()
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except WebSocketDisconnect:
                break
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        if user_id and user_id in connected_clients:
            try:
                connected_clients[user_id].remove(websocket)
            except ValueError:
                pass


async def notify_user(user_id: int, payload: dict):
    if user_id in connected_clients:
        dead = []
        for ws in connected_clients[user_id]:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                connected_clients[user_id].remove(ws)
            except ValueError:
                pass
