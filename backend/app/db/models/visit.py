import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Visit(Base):
    """SRS section 6: visits table -- the core record, one row per home visit.

    structured_json is Agent 1's output (FR-02.5); risk_score/risk_level are
    Agent 2's output (FR-03.1)."""

    __tablename__ = "visits"

    visit_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(String, ForeignKey("patients.patient_id"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(String, ForeignKey("workers.worker_id"), nullable=False, index=True)
    audio_url: Mapped[str] = mapped_column(String, nullable=True)
    transcript: Mapped[str] = mapped_column(Text, nullable=True)
    structured_json: Mapped[str] = mapped_column(Text, nullable=True)  # JSON string: Agent 1 output
    risk_score: Mapped[float] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str] = mapped_column(String, nullable=True)  # HIGH | MEDIUM | LOW
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
