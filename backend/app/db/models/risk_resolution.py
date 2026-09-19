from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.encryption import EncryptedString
from app.db.session import Base

class RiskResolution(Base):
    __tablename__ = "risk_resolutions"
    visit_id: Mapped[str] = mapped_column(String, ForeignKey("visits.visit_id"), primary_key=True)
    resolved_by: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
