import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class AuditLog(Base):
    """SRS section 6 + NFR-SC4: audit trail for every data access/modification."""

    __tablename__ = "audit_log"

    log_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "visit.create", "risk.override"
    record_id: Mapped[str] = mapped_column(String, nullable=True)
    record_type: Mapped[str] = mapped_column(String, nullable=True)  # e.g. "visit", "risk_flag"
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    ip_address: Mapped[str] = mapped_column(String, nullable=True)
    # e.g. {"previous_risk_level": "HIGH", "new_risk_level": "MEDIUM", "reason": "..."}
    # for a risk.override entry -- the human-readable "why", not just "what changed".
    details: Mapped[str] = mapped_column(Text, nullable=True)
