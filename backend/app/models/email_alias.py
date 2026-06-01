# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class EmailAlias(Base):
    __tablename__ = "email_aliases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_email = Column(String(255), nullable=False, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    destinations = Column(Text, nullable=False, comment="Comma-separated destination emails")
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    domain = relationship("Domain", back_populates="email_aliases")
