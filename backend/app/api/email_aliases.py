# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.audit import AuditLog

from app.core.database import get_db
from app.api.deps import get_current_user, require_admin
from app.models.email_alias import EmailAlias
from app.models.domain import Domain
from app.services.postfix_service import PostfixService
from app.schemas.email_alias import (
    EmailAliasCreate,
    EmailAliasUpdate,
    EmailAliasResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/aliases", tags=["Email Aliases"])


def _alias_to_response(a: EmailAlias) -> EmailAliasResponse:
    domain_name = None
    if a.domain:
        domain_name = a.domain.domain_name
    return EmailAliasResponse(
        id=a.id,
        source_email=a.source_email,
        domain_id=a.domain_id,
        domain_name=domain_name,
        destinations=a.destinations,
        description=a.description,
        is_active=a.is_active,
        created_at=a.created_at,
    )


@router.get("/", response_model=List[EmailAliasResponse])
async def list_aliases(
    domain_id: Optional[int] = Query(None),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(EmailAlias).options(selectinload(EmailAlias.domain)).offset(skip).limit(limit)
    if domain_id is not None:
        query = query.where(EmailAlias.domain_id == domain_id)
    query = query.order_by(EmailAlias.source_email)
    result = await db.execute(query)
    aliases = result.scalars().all()
    return [_alias_to_response(a) for a in aliases]


@router.get("/{alias_id}", response_model=EmailAliasResponse)
async def get_alias(
    alias_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EmailAlias).options(selectinload(EmailAlias.domain)).where(EmailAlias.id == alias_id)
    )
    alias = result.scalar_one_or_none()
    if not alias:
        raise HTTPException(status_code=404, detail="Alias not found")
    return _alias_to_response(alias)


@router.post("/", response_model=EmailAliasResponse, status_code=status.HTTP_201_CREATED)
async def create_alias(
    data: EmailAliasCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    domain_result = await db.execute(select(Domain).where(Domain.id == data.domain_id))
    domain = domain_result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=400, detail="Domain not found")

    existing = await db.execute(select(EmailAlias).where(EmailAlias.source_email == data.source_email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Alias with this source email already exists")

    alias = EmailAlias(
        source_email=data.source_email,
        domain_id=data.domain_id,
        destinations=data.destinations,
        description=data.description,
        is_active=data.is_active if data.is_active is not None else True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(alias)
    await db.flush()
    await db.refresh(alias)

    db.add(AuditLog(
        user_id=current_user.id,
        action="alias.create",
        resource_type="alias",
        resource_id=str(alias.id),
        details={"source_email": data.source_email, "destinations": data.destinations},
        created_at=datetime.now(timezone.utc),
    ))
    await db.flush()
    return _alias_to_response(alias)


@router.put("/{alias_id}", response_model=EmailAliasResponse)
async def update_alias(
    alias_id: int,
    data: EmailAliasUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EmailAlias).options(selectinload(EmailAlias.domain)).where(EmailAlias.id == alias_id)
    )
    alias = result.scalar_one_or_none()
    if not alias:
        raise HTTPException(status_code=404, detail="Alias not found")

    update_data = data.model_dump(exclude_unset=True)
    if "source_email" in update_data and update_data["source_email"] != alias.source_email:
        existing = await db.execute(select(EmailAlias).where(EmailAlias.source_email == update_data["source_email"]))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Alias with this source email already exists")
    for field, value in update_data.items():
        setattr(alias, field, value)
    db.add(alias)
    await db.flush()
    await db.refresh(alias)
    return _alias_to_response(alias)


@router.delete("/{alias_id}")
async def delete_alias(
    alias_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    result = await db.execute(select(EmailAlias).where(EmailAlias.id == alias_id))
    alias = result.scalar_one_or_none()
    if not alias:
        raise HTTPException(status_code=404, detail="Alias not found")

    db.add(AuditLog(
        user_id=current_user.id,
        action="alias.delete",
        resource_type="alias",
        resource_id=str(alias_id),
        details={"source_email": alias.source_email},
        created_at=datetime.now(timezone.utc),
    ))
    await db.delete(alias)
    await db.flush()
    return {"message": "Alias deleted successfully"}


@router.post("/sync-postfix")
async def sync_aliases_to_postfix(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    result = await db.execute(
        select(EmailAlias)
        .options(selectinload(EmailAlias.domain))
        .where(EmailAlias.is_active == True)
    )
    aliases = result.scalars().all()
    alias_map: dict[str, str] = {}
    for a in aliases:
        alias_map[a.source_email] = a.destinations

    postfix = PostfixService()
    ok = await postfix.sync_virtual_aliases(alias_map)

    db.add(AuditLog(
        user_id=current_user.id,
        action="alias.sync_postfix",
        resource_type="alias",
        details={"count": len(aliases)},
        created_at=datetime.now(timezone.utc),
    ))
    await db.flush()

    return {"success": ok, "synced_count": len(aliases), "message": "Aliases sincronizados com Postfix" if ok else "Falha ao sincronizar"}
