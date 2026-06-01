# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import logging
from typing import Dict, Any, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.models.user import User
from app.models.domain import Domain
from app.schemas.domain import DnsRecord

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/dns", tags=["DNS Management"])

CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"


@router.post("/cloudflare/test")
async def test_cloudflare(
    body: Dict[str, Any],
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    api_token = body.get("api_token", "")
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{CLOUDFLARE_API}/user/tokens/verify", headers=headers, timeout=15)
            data = resp.json()
            return {"success": resp.is_success, "data": data}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Cloudflare API error: {e}")


@router.post("/cloudflare/zones")
async def list_zones(
    body: Dict[str, Any],
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    api_token = body.get("api_token", "")
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{CLOUDFLARE_API}/zones", headers=headers, timeout=15)
            return resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Cloudflare API error: {e}")


@router.post("/cloudflare/records")
async def list_dns_records(
    body: Dict[str, Any],
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    api_token = body.get("api_token", "")
    zone_id = body.get("zone_id", "")
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{CLOUDFLARE_API}/zones/{zone_id}/dns_records",
                headers=headers,
                timeout=15,
            )
            return resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Cloudflare API error: {e}")


@router.post("/cloudflare/create-record")
async def create_dns_record(
    body: Dict[str, Any],
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    api_token = body.get("api_token", "")
    zone_id = body.get("zone_id", "")
    record = DnsRecord(**body.get("record", {}))
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    payload = {
        "type": record.type,
        "name": record.name,
        "content": record.value,
        "ttl": record.ttl or 300,
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{CLOUDFLARE_API}/zones/{zone_id}/dns_records",
                headers=headers,
                json=payload,
                timeout=15,
            )
            return resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Cloudflare API error: {e}")


@router.post("/cloudflare/delete-record")
async def delete_dns_record(
    body: Dict[str, Any],
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    api_token = body.get("api_token", "")
    zone_id = body.get("zone_id", "")
    record_id = body.get("record_id", "")
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.delete(
                f"{CLOUDFLARE_API}/zones/{zone_id}/dns_records/{record_id}",
                headers=headers,
                timeout=15,
            )
            return resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Cloudflare API error: {e}")


@router.post("/registrobr/check")
async def check_registrobr(
    domain: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    import asyncio, dns.asyncresolver
    result = {"domain": domain, "registrobr_status": "unknown", "whois_info": {}}
    try:
        txt_records = await dns.asyncresolver.resolve(f"{domain}.br", "TXT")
        for rec in txt_records:
            txt = "".join([s.decode() if isinstance(s, bytes) else s for s in rec.strings])
            result["whois_info"][rec.target.to_text()] = txt
    except Exception as e:
        logger.warning(f"DNS check failed for {domain}: {e}")
    return result


@router.post("/check-propagation")
async def check_propagation(
    record_type: str,
    record_name: str,
    expected_value: Optional[str] = None,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    import asyncio, dns.asyncresolver
    results = []
    nameservers = ["8.8.8.8", "1.1.1.1", "208.67.222.222"]

    async def check_ns(ns: str) -> Dict[str, Any]:
        try:
            resolver = dns.asyncresolver.Resolver()
            resolver.nameservers = [ns]
            answers = await resolver.resolve(record_name, record_type)
            values = [str(a) for a in answers]
            match = expected_value and any(expected_value in str(v) for v in values)
            return {"nameserver": ns, "values": values, "match": match}
        except Exception as e:
            return {"nameserver": ns, "error": str(e)}

    results = await asyncio.gather(*[check_ns(ns) for ns in nameservers])
    return {"record_type": record_type, "record_name": record_name, "results": results}


@router.post("/wizard")
async def dns_wizard(
    body: Dict[str, Any],
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    domain = body.get("domain", "")
    ip_address = body.get("ip_address", "")
    dkim_selector = body.get("dkim_selector", "default")
    api_token = body.get("api_token")
    zone_id = body.get("zone_id")
    result = await db.execute(select(Domain).where(Domain.domain_name == domain))
    domain_obj = result.scalar_one_or_none()
    if not domain_obj:
        raise HTTPException(
            status_code=404,
            detail=f"Domain '{domain}' not found in database. Add it first in Domains.",
        )

    expected_records = [
        {"type": "MX", "name": domain, "expected": f"mail.{domain}", "label": "MX Record"},
        {"type": "A", "name": f"mail.{domain}", "expected": ip_address, "label": "A Record (mail)"},
        {"type": "TXT", "name": domain, "expected": f"v=spf1 mx a:mail.{domain} -all", "label": "SPF Record"},
        {"type": "TXT", "name": f"{dkim_selector}._domainkey.{domain}", "expected": "v=DKIM1; h=sha256; p=<public_key>", "label": "DKIM Record"},
        {"type": "TXT", "name": f"_dmarc.{domain}", "expected": f"v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}", "label": "DMARC Record"},
    ]

    if api_token and zone_id:
        headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
        results = []
        async with httpx.AsyncClient() as client:
            for rec in expected_records:
                payload = {
                    "type": rec["type"],
                    "name": rec["name"],
                    "content": rec["expected"],
                    "ttl": 300,
                }
                try:
                    resp = await client.post(
                        f"{CLOUDFLARE_API}/zones/{zone_id}/dns_records",
                        headers=headers,
                        json=payload,
                        timeout=15,
                    )
                    cf_data = resp.json()
                    if resp.is_success and cf_data.get("success"):
                        results.append({
                            "type": rec["type"],
                            "name": rec["name"],
                            "expected": rec["expected"],
                            "actual": rec["expected"],
                            "status": "pass",
                            "label": rec["label"],
                        })
                    else:
                        errors = cf_data.get("errors", [{"message": "Unknown error"}])
                        results.append({
                            "type": rec["type"],
                            "name": rec["name"],
                            "expected": rec["expected"],
                            "actual": str(errors[0].get("message", "")),
                            "status": "fail",
                            "label": rec["label"],
                        })
                except Exception as e:
                    results.append({
                        "type": rec["type"],
                        "name": rec["name"],
                        "expected": rec["expected"],
                        "actual": str(e),
                        "status": "fail",
                        "label": rec["label"],
                    })
        return {
            "domain": domain,
            "ip_address": ip_address,
            "results": results,
            "message": "DNS records applied via Cloudflare.",
        }

    return {
        "domain": domain,
        "ip_address": ip_address,
        "results": [
            {
                "type": r["type"],
                "name": r["name"],
                "expected": r["expected"],
                "actual": "",
                "status": "warning",
                "label": r["label"],
            }
            for r in expected_records
        ],
        "message": "Suggested DNS records. Configure manually or provide api_token and zone_id from Cloudflare.",
    }
