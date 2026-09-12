import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedString
from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Patient(Base):
    """SRS section 6: patients table.

    name/phone are encrypted at rest (NFR-SC1, see app/core/encryption.py).
    village stays plaintext -- it backs the district heatmap's village
    grouping (FR-08.1) and encryption would break that aggregation."""

    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    worker_id: Mapped[str] = mapped_column(String, ForeignKey("workers.worker_id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=True)
    gender: Mapped[str] = mapped_column(String, nullable=True)
    village: Mapped[str] = mapped_column(String, nullable=True)
    phone: Mapped[str] = mapped_column(EncryptedString, nullable=True)
    pregnancy_stage: Mapped[str] = mapped_column(String, nullable=True)  # e.g. "7 months" | None
    # Baseline vitals recorded at registration -- the reference point later
    # visits are read against. Per-visit measurements live on the visit's
    # structured_json and are what risk scoring actually uses; these are
    # not scored on their own. Fasting and random sugar stay separate
    # because the NHM cutoffs differ (>=126 vs >=200 mg/dL).
    bp_systolic: Mapped[int] = mapped_column(Integer, nullable=True)
    bp_diastolic: Mapped[int] = mapped_column(Integer, nullable=True)
    blood_sugar_fasting: Mapped[int] = mapped_column(Integer, nullable=True)
    blood_sugar_random: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
