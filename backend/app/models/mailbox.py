# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
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


class Mailbox(Base):
    __tablename__ = "mailboxes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    password_hash = Column(String(255), nullable=False)
    password_encrypted = Column(Text, nullable=True)
    quota_limit_mb = Column(Integer, default=0, comment="0=unlimited")
    quota_used_mb = Column(BigInteger, default=0)
    is_active = Column(Boolean, default=True)
    forward_to = Column(Text, nullable=True)
    auto_responder_enabled = Column(Boolean, default=False)
    auto_responder_subject = Column(String(255), nullable=True)
    auto_responder_body = Column(Text, nullable=True)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    domain = relationship("Domain", back_populates="mailboxes")
