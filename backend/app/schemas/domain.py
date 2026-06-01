# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class DomainCreate(BaseModel):
    domain_name: str = Field(..., min_length=1, max_length=255)
    status: Optional[str] = "pending"
    quota_template_id: Optional[int] = None
    cloudflare_zone_id: Optional[str] = None
    cloudflare_token: Optional[str] = None
    dns_mode: Optional[str] = "manual"
    dkim_selector: Optional[str] = "default"
    expires_at: Optional[datetime] = None


class DomainUpdate(BaseModel):
    domain_name: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[str] = None
    quota_template_id: Optional[int] = None
    cloudflare_zone_id: Optional[str] = None
    dkim_selector: Optional[str] = None
    expires_at: Optional[datetime] = None
    dns_verified: Optional[bool] = None
    registrobr_status: Optional[str] = None


class DomainResponse(BaseModel):
    id: int
    domain_name: str
    status: str
    quota_template_id: Optional[int] = None
    cloudflare_zone_id: Optional[str] = None
    dkim_selector: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    dns_verified: bool
    registrobr_status: Optional[str] = None
    mailbox_count: int = 0
    setup_steps: Optional[dict] = None
    quota_per_mailbox: Optional[int] = None
    quota_total_gb: Optional[float] = 0
    quota_used_gb: Optional[float] = 0
    quota_used_pct: Optional[float] = 0
    mailbox_limit: Optional[int] = 0
    dkim_public_key: Optional[str] = None
    spf_value: Optional[str] = None
    dmarc_value: Optional[str] = None

    model_config = {"from_attributes": True}


class QuotaTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    mailbox_limit_mb: Optional[int] = 0
    storage_limit_mb: Optional[int] = 0
    max_mailboxes: Optional[int] = 0
    description: Optional[str] = None
    is_default: Optional[bool] = False


class QuotaTemplateResponse(BaseModel):
    id: int
    name: str
    mailbox_limit_mb: int
    storage_limit_mb: int
    max_mailboxes: int
    description: Optional[str] = None
    is_default: bool

    model_config = {"from_attributes": True}


class DnsRecord(BaseModel):
    type: str = Field(..., pattern=r"^(A|AAAA|CNAME|MX|TXT|SRV|NS)$")
    name: str
    value: str
    ttl: Optional[int] = 300


class DomainDnsStatus(BaseModel):
    domain_id: int
    domain_name: str
    has_mx: bool = False
    has_spf: bool = False
    has_dkim: bool = False
    has_dmarc: bool = False
    mx_correct: bool = False
    spf_correct: bool = False
    dkim_correct: bool = False
    dmarc_correct: bool = False
    dns_verified: bool = False
