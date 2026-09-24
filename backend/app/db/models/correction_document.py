import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedString
from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class CorrectionDocument(Base):
    """The proof behind a corrected patient record.

    Changing the name on a health record is not a typo fix once that
    record has been used -- a referral letter has gone to a PHC under it,
    an HMIS return has counted her under it. So past the first day it
    stops being an edit and becomes an official correction, which is a
    thing the district officer does against a document: an Aadhaar card,
    an MCP card, a voter ID.

    The file lives in this table rather than on disk because the disk a
    managed host gives you is wiped on every deploy -- a correction whose
    evidence disappears on the next release is not evidence. Bytes in the
    database survive restarts, redeploys and a database restore, which is
    what "on the record" has to mean.
    """

    __tablename__ = "correction_documents"

    document_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(
        String, ForeignKey("patients.patient_id"), nullable=False, index=True
    )

    # The file exactly as it was handed over. Deliberately not re-encoded
    # or thumbnailed: this is a legal artefact, and the copy on the record
    # should be the copy that was produced.
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Encrypted: a filename is routinely somebody's name plus the document
    # type ("meena-aadhaar.jpg"), which is the pairing the rest of this
    # schema goes to some trouble not to leave lying in the clear.
    filename: Mapped[str] = mapped_column(EncryptedString, nullable=True)

    # What the document was produced to justify.
    changed_fields: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    reason: Mapped[str] = mapped_column(EncryptedString, nullable=False)

    uploaded_by: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_by_name: Mapped[str] = mapped_column(String, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
