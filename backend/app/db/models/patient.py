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

    # ── Who she is, formally ────────────────────────────────────────────
    #
    # The number on the Mother and Child Protection card she keeps in her
    # own handbag, issued when the sub-centre registers her. Twelve
    # digits, unique across the deployment.
    #
    # Optional on purpose. An ASHA meeting a woman at her door before the
    # sub-centre has registered her has no RCH number to type, and
    # refusing the visit until she does would push the work back onto
    # paper -- the exact failure this product exists to remove.
    rch_number: Mapped[str] = mapped_column(String, unique=True, nullable=True, index=True)

    # A keyed hash of her phone number -- see app/services/identity.py.
    #
    # `phone` above is AES-GCM encrypted with a random nonce, so the same
    # number never encrypts to the same bytes twice and equality lookups
    # are impossible. That is the right property for confidentiality, and
    # it is exactly why two ASHAs in neighbouring hamlets could both
    # register the same pregnant woman with nothing noticing. This gives
    # equality back without giving plaintext back.
    phone_hash: Mapped[str] = mapped_column(String, nullable=True, index=True)

    # ── Where she is ────────────────────────────────────────────────────
    #
    # `village` is what the ASHA typed, and is what gets displayed.
    # `village_code` is the key it groups by, because "Wagholi",
    # "wagholi" and " Wagholi " were three villages to the district
    # heatmap.
    village_code: Mapped[str] = mapped_column(String, nullable=True, index=True)

    # The area she belongs to -- not the area of whoever is treating her.
    #
    # Her sub-centre used to be read off her ASHA, so when a worker moved,
    # every patient silently moved sub-centre with her: a woman who had
    # not left her village changed rows on a district report because
    # somebody else changed jobs. Set once at registration, and left alone
    # when her caseload is reassigned.
    sub_centre_id: Mapped[str] = mapped_column(String, nullable=True, index=True)
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
