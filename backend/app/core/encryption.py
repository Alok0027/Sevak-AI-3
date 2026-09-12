"""NFR-SC1: "All patient data encrypted at rest" -- AES-256-GCM applied at
the SQLAlchemy column level so every ORM read/write goes through it
transparently, with no changes needed anywhere else in the app.

Scope is deliberate, not exhaustive: only fields that are genuine patient
PII/clinical content *and* are never used in a server-side SQL filter or
GROUP BY get encrypted --

    Patient.name, Patient.phone, Visit.transcript, Visit.structured_json

Two fields that look like candidates are deliberately left plaintext:
  - Worker.phone is the login lookup key (`WHERE phone = ?` in
    app/api/routes/auth.py) -- AES-GCM uses a random nonce per encryption,
    so the same phone number never encrypts to the same ciphertext twice,
    which makes equality lookups impossible without a separate blind-index
    scheme. Out of scope for this pass.
  - Patient.village backs the district risk heatmap's village grouping
    (FR-08.1, app/api/routes/dashboard.py) -- encrypting it would break
    that aggregation for the same reason.
"""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings

# Every ciphertext is stored with this prefix so decrypt_field() can tell an
# already-encrypted value apart from a pre-migration plaintext leftover, and
# so scripts/encrypt_existing_data.py can skip rows it already handled.
_MARKER = "enc:v1:"


class EncryptionKeyError(RuntimeError):
    pass


def _get_key() -> bytes:
    settings = get_settings()
    key_b64 = settings.encryption_key
    if not key_b64:
        raise EncryptionKeyError(
            "ENCRYPTION_KEY is not set. Generate one with "
            "`python scripts/generate_encryption_key.py` and add it to backend/.env."
        )
    try:
        key = base64.urlsafe_b64decode(key_b64)
    except Exception as exc:  # noqa: BLE001 -- surface as our own error type
        raise EncryptionKeyError("ENCRYPTION_KEY is not valid urlsafe-base64.") from exc
    if len(key) != 32:
        raise EncryptionKeyError("ENCRYPTION_KEY must decode to exactly 32 bytes (AES-256).")
    return key


def encrypt_field(plaintext: str | None) -> str | None:
    """Encrypt one value for storage. None passes through untouched (a NULL
    column stays NULL, it was never "patient data" to protect)."""
    if plaintext is None:
        return None
    aesgcm = AESGCM(_get_key())
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return _MARKER + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_field(value: str | None) -> str | None:
    """Decrypt one stored value. A value without the marker is treated as a
    pre-migration plaintext leftover and returned as-is rather than raising --
    see scripts/encrypt_existing_data.py, which is what actually migrates it."""
    if value is None:
        return None
    if not value.startswith(_MARKER):
        return value
    raw = base64.urlsafe_b64decode(value[len(_MARKER):])
    nonce, ciphertext = raw[:12], raw[12:]
    aesgcm = AESGCM(_get_key())
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


class EncryptedString(TypeDecorator):
    """Drop-in column type: transparent AES-256-GCM encryption on write,
    decryption on read. Backed by Text (not the original column's type) so
    Postgres/SQLite never truncate the longer base64 ciphertext."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_field(value)

    def process_result_value(self, value, dialect):
        return decrypt_field(value)
