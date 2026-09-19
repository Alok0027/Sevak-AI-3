import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.core.encryption import EncryptedString


def _uuid() -> str:
    return str(uuid.uuid4())


class SyncQueueEntry(Base):
    """SRS section 6: sync_queue table -- server-side mirror of the mobile
    app's offline queue, written by POST /api/v1/sync/batch (FR-01.3, FR-07.1)."""

    __tablename__ = "sync_queue"

    queue_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    worker_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "visit"
    record_json: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
