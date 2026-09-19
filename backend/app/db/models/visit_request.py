"""Durable request identity shared by online submission and offline replay."""
from datetime import datetime, timezone
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.core.encryption import EncryptedString
from app.db.session import Base


class VisitRequest(Base):
    __tablename__ = "visit_requests"
    request_key: Mapped[str] = mapped_column(String, primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String, nullable=False)
    response_json: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
