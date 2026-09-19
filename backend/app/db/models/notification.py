from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.encryption import EncryptedString
from app.db.session import Base


class Notification(Base):
    __tablename__ = "notification_outbox"
    action_id: Mapped[str] = mapped_column(String, ForeignKey("actions.action_id"), primary_key=True)
    payload_json: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    approved_by: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    provider_id: Mapped[str | None] = mapped_column(String, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
