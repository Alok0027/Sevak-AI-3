import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class RiskFlag(Base):
    """SRS section 6: risk_flags table. drivers_json holds Agent 2's explainable
    reasons (FR-03.2). escalated_at / actioned_at back Agent 5 (FR-06.1)."""

    __tablename__ = "risk_flags"

    flag_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    visit_id: Mapped[str] = mapped_column(String, ForeignKey("visits.visit_id"), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String, nullable=False)  # HIGH | MEDIUM | LOW
    drivers_json: Mapped[str] = mapped_column(Text, nullable=True)  # JSON array of plain-language reasons
    overridden_by: Mapped[str] = mapped_column(String, nullable=True)  # worker_id of ANM who overrode (FR-03.3)
    override_reason: Mapped[str] = mapped_column(Text, nullable=True)
    escalated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    actioned_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
