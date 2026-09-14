"""JWT issuing/verification and password hashing (FR-08 roles, NFR-SC3 RBAC)."""
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

# pbkdf2_sha256 rather than bcrypt: worker auth is a short numeric PIN (not a
# password), and this sidesteps bcrypt's 72-byte-input / build-toolchain
# quirks on constrained deployment targets while staying a real salted hash.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_pin(pin: str) -> str:
    return pwd_context.hash(pin)


def verify_pin(pin: str, hashed: str) -> bool:
    return pwd_context.verify(pin, hashed)


# Roles that work in the field, on their own phone, out of signal.
FIELD_ROLES = frozenset({"asha"})


def token_lifetime_minutes(role: str) -> int:
    """How long a token lasts, by who is holding it.

    A supervisor signs in to a web dashboard, often on a shared computer, so
    a short session is the safer default and costs her nothing -- she is
    online by definition.

    An ASHA is the opposite case. FR-07.1 says the app works fully offline
    and FR-01.3 says queued visits sync when signal returns; a single
    eight-hour window made both untrue. A worker who spent a day in a
    village with no bars came back to a dead token, and because
    /sync/batch needs it, her queued visits could not be pushed at all --
    the app looked like it had eaten them. She had to sign out and back in
    to recover, which is not something the offline story should ever
    require, and not something she would think to try.

    The trade-off is honest: a long-lived token on a lost phone is a long
    window of access. The app re-issues it on every online start (see
    POST /auth/refresh), so the clock resets constantly in practice and
    only a phone that is lost *and* offline holds a stale one.
    """
    settings = get_settings()
    return (
        settings.field_token_expire_minutes
        if role in FIELD_ROLES
        else settings.access_token_expire_minutes
    )


def create_access_token(subject: str, role: str, extra_claims: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=token_lifetime_minutes(role))
    payload: dict[str, Any] = {"sub": subject, "role": role, "exp": expire}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc
