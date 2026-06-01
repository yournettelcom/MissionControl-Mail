# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, ForeignKey, BigInteger,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class QuotaTemplate(Base):
    __tablename__ = "quota_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    mailbox_limit_mb = Column(Integer, default=0, comment="0=unlimited")
    storage_limit_mb = Column(Integer, default=0, comment="0=unlimited")
    max_mailboxes = Column(Integer, default=0, comment="0=unlimited")
    description = Column(Text, nullable=True)
    is_default = Column(Boolean, default=False)

    domains = relationship("Domain", back_populates="quota_template")


class Domain(Base):
    __tablename__ = "domains"

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain_name = Column(String(255), unique=True, nullable=False, index=True)
    status = Column(String(20), default="pending", comment="active|inactive|pending")
    quota_template_id = Column(Integer, ForeignKey("quota_templates.id"), nullable=True)
    cloudflare_zone_id = Column(String(255), nullable=True)
    dkim_selector = Column(String(100), default="default")
    dkim_private_key = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime, nullable=True)
    dns_verified = Column(Boolean, default=False)
    registrobr_status = Column(Text, nullable=True)

    quota_template = relationship("QuotaTemplate", back_populates="domains")
    mailboxes = relationship("Mailbox", back_populates="domain", cascade="all, delete-orphan")
    email_aliases = relationship("EmailAlias", back_populates="domain", cascade="all, delete-orphan")
