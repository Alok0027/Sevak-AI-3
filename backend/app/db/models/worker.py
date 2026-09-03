import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Worker(Base):
    """SRS section 6: workers table. Covers all 4 roles (FR-08 / table 4):
    asha, anm, bmo, admin. `role` gates permissions in app/api/deps.py."""

    __tablename__ = "workers"

    worker_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    pin_hash: Mapped[str] = mapped_column(String, nullable=False)
    language_pref: Mapped[str] = mapped_column(String, default="hi")  # ISO-ish code: hi, mr, ta, te, bn
    sub_centre_id: Mapped[str] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, default="asha")  # asha | anm | bmo | admin
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
