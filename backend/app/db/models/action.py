import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Action(Base):
    """SRS section 6: actions table. One row per Agent 3 output: referral
    letter, WhatsApp draft, or follow-up task (FR-04.1 / FR-04.2 / FR-04.3)."""

    __tablename__ = "actions"

    action_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    visit_id: Mapped[str] = mapped_column(String, ForeignKey("visits.visit_id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String, nullable=False)  # referral | whatsapp | followup
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft | sent | done | cancelled
    due_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)  # follow-up due date (FR-04.3)
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
