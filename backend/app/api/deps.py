"""NFR-SC3: JWT auth + role-based access, enforced server-side on every endpoint."""
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db

bearer_scheme = HTTPBearer()


class CurrentUser:
    def __init__(self, worker_id: str, role: str):
        self.worker_id = worker_id
        self.role = role


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> CurrentUser:
    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return CurrentUser(worker_id=payload["sub"], role=payload["role"])


def require_roles(*allowed_roles: str):
    def _checker(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not permitted to access this endpoint",
            )
        return user

    return _checker


DbSession = Annotated[Session, Depends(get_db)]


def get_supervisor_scope(user: CurrentUser, db: Session) -> str | None:
    """SRS table 4: an ANM 'cannot access district-level data' -- every
    district-wide endpoint (worker roster, escalations, analytics) must
    scope an ANM caller down to their own sub_centre_id. BMO/Admin get None
    (no restriction), matching their district-wide view.

    Raises 500 rather than silently returning unscoped data if an ANM's
    worker row is somehow missing -- fail closed on a scoping bug, don't
    leak district data."""
    if user.role != "anm":
        return None
    from app.db.models.worker import Worker  # local import: avoid circular import at module load

    worker = db.query(Worker).filter(Worker.worker_id == user.worker_id).first()
    if worker is None:
        raise HTTPException(status_code=500, detail="ANM worker record not found -- cannot scope request")
    return worker.sub_centre_id
