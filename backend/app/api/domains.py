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
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload

from app.models.user import User

from app.core.database import get_db
from app.api.deps import get_current_user, require_admin
from app.models.domain import Domain, QuotaTemplate
from app.models.mailbox import Mailbox
from app.schemas.domain import (
    DomainCreate,
    DomainUpdate,
    DomainResponse,
    QuotaTemplateCreate,
    QuotaTemplateResponse,
    DomainDnsStatus,
)
from app.services.postfix_service import PostfixService
from app.services.dns_service import DnsService
from app.services.dovecot_service import DovecotService
from app.services.cloudflare_service import CloudflareService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/domains", tags=["Domains"])


async def _domain_to_response(domain: Domain, db: AsyncSession, setup_steps: dict | None = None, pre_count: int | None = None, pre_used: int | None = None) -> DomainResponse:
    if pre_count is not None:
        mailbox_count = pre_count
    else:
        count_result = await db.execute(
            select(func.count(Mailbox.id)).where(Mailbox.domain_id == domain.id)
        )
        mailbox_count = count_result.scalar() or 0

    if pre_used is not None:
        quota_used_mb = pre_used
    else:
        used_result = await db.execute(
            select(func.coalesce(func.sum(Mailbox.quota_used_mb), 0)).where(Mailbox.domain_id == domain.id)
        )
        quota_used_mb = used_result.scalar() or 0

    quota_template = domain.quota_template
    quota_per_mailbox = None
    quota_total_gb = 0.0
    mailbox_limit = 0
    storage_limit_mb = 0
    if quota_template:
        quota_per_mailbox = quota_template.mailbox_limit_mb
        quota_total_gb = round(quota_template.storage_limit_mb / 1024, 2) if quota_template.storage_limit_mb > 0 else 0
        mailbox_limit = quota_template.max_mailboxes
        storage_limit_mb = quota_template.storage_limit_mb or 0
    quota_used_gb = round(quota_used_mb / 1024, 2)
    quota_used_pct = round((quota_used_mb / storage_limit_mb) * 100, 1) if storage_limit_mb > 0 else 0.0

    dkim_public_key = None
    if domain.dkim_private_key:
        import re
        match = re.search(r'-----BEGIN PUBLIC KEY-----(.+?)-----END PUBLIC KEY-----', domain.dkim_private_key, re.DOTALL)
        if match:
            dkim_public_key = match.group(0).strip()

    domain_name = domain.domain_name
    spf_value = f"v=spf1 mx a:mail.{domain_name} -all"
    dmarc_value = f"v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain_name}"

    return DomainResponse(
        id=domain.id,
        domain_name=domain.domain_name,
        status=domain.status,
        quota_template_id=domain.quota_template_id,
        cloudflare_zone_id=domain.cloudflare_zone_id,
        dkim_selector=domain.dkim_selector,
        created_at=domain.created_at,
        expires_at=domain.expires_at,
        dns_verified=domain.dns_verified,
        registrobr_status=domain.registrobr_status,
        mailbox_count=mailbox_count,
        setup_steps=setup_steps,
        quota_per_mailbox=quota_per_mailbox,
        quota_total_gb=quota_total_gb,
        quota_used_gb=quota_used_gb,
        quota_used_pct=quota_used_pct,
        mailbox_limit=mailbox_limit,
        dkim_public_key=dkim_public_key,
        spf_value=spf_value,
        dmarc_value=dmarc_value,
    )


@router.get("/templates", response_model=List[QuotaTemplateResponse])
async def list_templates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(QuotaTemplate))
    return result.scalars().all()


@router.post("/templates", response_model=QuotaTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: QuotaTemplateCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if data.is_default:
        await db.execute(
            QuotaTemplate.__table__.update().values(is_default=False).where(QuotaTemplate.is_default == True)
        )
    template = QuotaTemplate(**data.model_dump())
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


@router.put("/templates/{template_id}", response_model=QuotaTemplateResponse)
async def update_template(
    template_id: int,
    data: QuotaTemplateCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(QuotaTemplate).where(QuotaTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if data.is_default and not template.is_default:
        await db.execute(
            QuotaTemplate.__table__.update().values(is_default=False).where(QuotaTemplate.is_default == True)
        )
    for field, value in data.model_dump().items():
        setattr(template, field, value)
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    result = await db.execute(select(QuotaTemplate).where(QuotaTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(template)
    await db.flush()
    return {"message": "Template deleted successfully"}


@router.get("/", response_model=List[DomainResponse])
async def list_domains(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Domain).options(selectinload(Domain.mailboxes)).offset(skip).limit(limit)
    if status_filter:
        query = query.where(Domain.status == status_filter)
    result = await db.execute(query)
    domains = result.scalars().all()
    if not domains:
        return []
    domain_ids = [d.id for d in domains]
    count_query = select(Mailbox.domain_id, func.count(Mailbox.id)).where(Mailbox.domain_id.in_(domain_ids)).group_by(Mailbox.domain_id)
    count_result = await db.execute(count_query)
    counts = dict(count_result.all())
    sum_query = select(Mailbox.domain_id, func.coalesce(func.sum(Mailbox.quota_used_mb), 0)).where(Mailbox.domain_id.in_(domain_ids)).group_by(Mailbox.domain_id)
    sum_result = await db.execute(sum_query)
    sums = dict(sum_result.all())
    return [await _domain_to_response(d, db, pre_count=counts.get(d.id, 0), pre_used=sums.get(d.id, 0)) for d in domains]


@router.post("/", response_model=DomainResponse, status_code=status.HTTP_201_CREATED)
async def create_domain(
    data: DomainCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(Domain).where(Domain.domain_name == data.domain_name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Domain already exists")

    if data.quota_template_id:
        t_result = await db.execute(select(QuotaTemplate).where(QuotaTemplate.id == data.quota_template_id))
        if not t_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Quota template not found")

    domain = Domain(
        domain_name=data.domain_name,
        status="setting_up",
        quota_template_id=data.quota_template_id,
        cloudflare_zone_id=data.cloudflare_zone_id,
        dkim_selector=data.dkim_selector or "default",
        created_at=datetime.now(timezone.utc),
        expires_at=data.expires_at,
    )
    db.add(domain)
    await db.flush()
    await db.refresh(domain)

    postfix = PostfixService()
    dns_svc = DnsService()
    domain_name = data.domain_name
    steps: dict[str, Any] = {}
    setup_ok = True

    try:
        vmail_base = "/opt/missioncontrol/vmail"
        os.makedirs(vmail_base, exist_ok=True)
        vmail_path = f"{vmail_base}/{domain_name}"
        os.makedirs(vmail_path, exist_ok=True)
        steps["vmail_directory"] = {"success": True, "path": vmail_path}
    except Exception as e:
        steps["vmail_directory"] = {"success": False, "error": str(e)}
        setup_ok = False

    try:
        key_private, key_public = await dns_svc.generate_dkim_keypair()
        domain.dkim_private_key = key_private
        selector = data.dkim_selector or "default"
        steps["dkim_keys"] = {"success": True, "selector": selector}
    except Exception as e:
        steps["dkim_keys"] = {"success": False, "error": str(e)}
        setup_ok = False

    try:
        vd_ok = await postfix.add_virtual_domain(domain_name)
        steps["postfix"] = {"success": vd_ok}
    except PermissionError:
        steps["postfix"] = {"success": False, "note": "Postfix config requires sudo - configure manually"}
    except Exception as e:
        steps["postfix"] = {"success": False, "error": str(e)}
        setup_ok = False

    if data.dns_mode == "auto" and data.cloudflare_token:
        try:
            dns_result = await dns_svc.wizard(
                domain=domain_name,
                mail_server_hostname=f"mail.{domain_name}",
                cloudflare_token=data.cloudflare_token,
            )
            steps["dns_wizard"] = dns_result
            if dns_result.get("status") == "completed":
                zone_id = (
                    dns_result.get("steps", {})
                    .get("zone_found", {})
                    .get("zone_id")
                )
                if zone_id:
                    domain.cloudflare_zone_id = zone_id
                    steps["dns_wizard"]["note"] = "DNS records configured via Cloudflare"
        except Exception as e:
            steps["dns_wizard"] = {"success": False, "error": str(e)}

    domain.status = "active" if setup_ok else "error"
    db.add(domain)
    await db.flush()
    await db.refresh(domain)

    return await _domain_to_response(domain, db, setup_steps=steps)


@router.get("/{domain_id}", response_model=DomainResponse)
async def get_domain(
    domain_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    return await _domain_to_response(domain, db)


@router.put("/{domain_id}", response_model=DomainResponse)
async def update_domain(
    domain_id: int,
    data: DomainUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(domain, field, value)
    db.add(domain)
    await db.flush()
    return await _domain_to_response(domain, db)


@router.delete("/{domain_id}")
async def delete_domain(
    domain_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    await db.delete(domain)
    await db.flush()
    return {"message": "Domain deleted successfully"}


@router.post("/{domain_id}/verify-dns")
async def verify_domain_dns(
    domain_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    import asyncio, dns.asyncresolver
    domain_name = domain.domain_name
    checks = {"mx": False, "spf": False, "dkim": False, "dmarc": False}
    dkim_domain = f"{domain.dkim_selector}._domainkey.{domain_name}"
    dmarc_domain = f"_dmarc.{domain_name}"

    async def check_mx():
        try:
            await dns.asyncresolver.resolve(domain_name, "MX")
            checks["mx"] = True
        except Exception as e:
            logger.warning(f"DNS MX check failed for {domain_name}: {e}")

    async def check_spf():
        try:
            txt_records = await dns.asyncresolver.resolve(domain_name, "TXT")
            for rec in txt_records:
                txt = "".join([s.decode() if isinstance(s, bytes) else s for s in rec.strings])
                if "v=spf1" in txt:
                    checks["spf"] = True
        except Exception as e:
            logger.warning(f"DNS SPF check failed for {domain_name}: {e}")

    async def check_dkim():
        try:
            await dns.asyncresolver.resolve(dkim_domain, "TXT")
            checks["dkim"] = True
        except Exception as e:
            logger.warning(f"DNS DKIM check failed for {domain_name}: {e}")

    async def check_dmarc():
        try:
            await dns.asyncresolver.resolve(dmarc_domain, "TXT")
            checks["dmarc"] = True
        except Exception as e:
            logger.warning(f"DNS DMARC check failed for {domain_name}: {e}")

    await asyncio.gather(check_mx(), check_spf(), check_dkim(), check_dmarc())

    all_ok = all(checks.values())
    domain.dns_verified = all_ok
    db.add(domain)
    await db.flush()

    return {"domain": domain_name, "checks": checks, "verified": all_ok}


@router.get("/{domain_id}/dns-status", response_model=DomainDnsStatus)
async def get_dns_status(
    domain_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    import asyncio, dns.asyncresolver
    domain_name = domain.domain_name
    has_mx = has_spf = has_dkim = has_dmarc = False
    mx_correct = spf_correct = dkim_correct = dmarc_correct = False
    dkim_domain = f"{domain.dkim_selector}._domainkey.{domain_name}"
    dmarc_domain = f"_dmarc.{domain_name}"

    async def check_mx():
        nonlocal has_mx, mx_correct
        try:
            await dns.asyncresolver.resolve(domain_name, "MX")
            has_mx = mx_correct = True
        except Exception as e:
            logger.warning(f"DNS MX check failed for {domain_name}: {e}")

    async def check_spf():
        nonlocal has_spf, spf_correct
        try:
            txt_records = await dns.asyncresolver.resolve(domain_name, "TXT")
            for rec in txt_records:
                txt = "".join([s.decode() if isinstance(s, bytes) else s for s in rec.strings])
                if "v=spf1" in txt:
                    has_spf = spf_correct = True
        except Exception as e:
            logger.warning(f"DNS SPF check failed for {domain_name}: {e}")

    async def check_dkim():
        nonlocal has_dkim, dkim_correct
        try:
            await dns.asyncresolver.resolve(dkim_domain, "TXT")
            has_dkim = dkim_correct = True
        except Exception as e:
            logger.warning(f"DNS DKIM check failed for {domain_name}: {e}")

    async def check_dmarc():
        nonlocal has_dmarc, dmarc_correct
        try:
            await dns.asyncresolver.resolve(dmarc_domain, "TXT")
            has_dmarc = dmarc_correct = True
        except Exception as e:
            logger.warning(f"DNS DMARC check failed for {domain_name}: {e}")

    await asyncio.gather(check_mx(), check_spf(), check_dkim(), check_dmarc())

    return DomainDnsStatus(
        domain_id=domain.id,
        domain_name=domain.domain_name,
        has_mx=has_mx,
        has_spf=has_spf,
        has_dkim=has_dkim,
        has_dmarc=has_dmarc,
        mx_correct=mx_correct,
        spf_correct=spf_correct,
        dkim_correct=dkim_correct,
        dmarc_correct=dmarc_correct,
        dns_verified=domain.dns_verified,
    )


@router.post("/{domain_id}/sync-cloudflare")
async def sync_cloudflare(
    domain_id: int,
    body: Dict[str, Any],
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    cloudflare_token = body.get("cloudflare_token", "")
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    if not domain.cloudflare_zone_id:
        raise HTTPException(status_code=400, detail="Cloudflare zone ID not configured")
    try:
        dns_svc = DnsService()
        wizard_result = await dns_svc.wizard(
            domain=domain.domain_name,
            mail_server_hostname=f"mail.{domain.domain_name}",
            cloudflare_token=cloudflare_token,
        )
        return wizard_result
    except Exception as e:
        logger.error(f"Cloudflare sync failed for {domain.domain_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Cloudflare sync failed: {str(e)}")
