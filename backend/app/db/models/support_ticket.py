import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedString
from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class SupportTicket(Base):
    """A problem an ASHA reported from the Help screen.

    The EOI deck names user adoption as a key risk and "training &
    onboarding" as the mitigation. A worker who cannot get the mic to work
    at a doorstep has, until now, had nowhere to say so -- she abandons the
    visit and writes it in her paper register, and nobody upstream ever
    learns the app failed her. This table is where that goes instead.

    `message` is encrypted at rest like every other free-text field she can
    type into (NFR-SC1). She will not keep clinical detail out of it just
    because the label says "technical problem" -- "recording पल्लवी's BP
    keeps failing" is a patient name in a support ticket.
    """

    __tablename__ = "support_tickets"

    ticket_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    worker_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # A short tag from a fixed list the app offers ("microphone", "sync",
    # "transcription", "login", "other"), so the admin panel can group them
    # without reading every message.
    category: Mapped[str] = mapped_column(String, nullable=False, default="other")
    message: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    # What she was using when it broke. Filled by the app, not typed: the
    # first question support would otherwise have to ask her by phone.
    app_version: Mapped[str] = mapped_column(String, nullable=True)
    device_info: Mapped[str] = mapped_column(String, nullable=True)
    language: Mapped[str] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(String, nullable=False, default="open")  # open | resolved
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[str] = mapped_column(String, nullable=True)
    resolution_note: Mapped[str] = mapped_column(Text, nullable=True)
