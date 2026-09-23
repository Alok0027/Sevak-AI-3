import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedString
from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class RiskFlag(Base):
    """SRS section 6: risk_flags table. drivers_json holds Agent 2's explainable
    reasons (FR-03.2). escalated_at / actioned_at back Agent 5 (FR-06.1).

    `drivers_json` and `override_reason` are encrypted at rest (NFR-SC1):
    the drivers quote her actual readings ("BP 167/105") and the override
    reason is free text a supervisor wrote about her case. `risk_level` is
    deliberately left plaintext -- the dashboard, the escalation queue and
    the HMIS aggregation all filter and group by it in SQL, and AES-GCM's
    random nonce makes that impossible on an encrypted column."""

    __tablename__ = "risk_flags"

    flag_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    visit_id: Mapped[str] = mapped_column(String, ForeignKey("visits.visit_id"), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String, nullable=False)  # HIGH | MEDIUM | LOW
    drivers_json: Mapped[str] = mapped_column(EncryptedString, nullable=True)  # JSON array of plain-language reasons
    overridden_by: Mapped[str] = mapped_column(String, nullable=True)  # worker_id of ANM who overrode (FR-03.3)
    override_reason: Mapped[str] = mapped_column(EncryptedString, nullable=True)
    escalated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    actioned_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
