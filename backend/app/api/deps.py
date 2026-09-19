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
    db: Annotated[Session, Depends(get_db)],
) -> CurrentUser:
    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    from app.db.models.worker import Worker

    worker = db.get(Worker, payload.get("sub")) if payload.get("sub") else None
    if worker is None or worker.status != "active":
        raise HTTPException(status_code=401, detail="Account is not active")
    # A signed token identifies a session; current database permissions
    # remain authoritative after suspension or a role change.
    return CurrentUser(worker_id=worker.worker_id, role=worker.role)


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
    if worker is None or not worker.sub_centre_id or not worker.sub_centre_id.strip():
        raise HTTPException(status_code=403, detail="ANM has no assigned sub-centre")
    return worker.sub_centre_id


def visible_sub_centres(user: CurrentUser, db: Session) -> list[str] | None:
    """Every sub-centre this caller may read. None means unrestricted.

    SRS table 4 gives the two supervisors different reach, and until this
    existed only one of them was actually enforced:

    - An ANM sees her own sub-centre. ("Cannot access district-level
      data.")
    - A BMO sees the sub-centres in her own district, and no further.
      ("District-level health authority overseeing multiple sub-centres.")
      This used to return None for a BMO -- no filter at all -- which in
      a single-district demo database looks identical to district scoping
      and in a real multi-district deployment means every BMO in the
      state can read every other district's patients.
    - An Admin is unrestricted here, because the admin role administers
      the system rather than a place. (Note that SRS table 4 also says an
      Admin has *no* patient record access at all; that is a separate
      gap, not one this function can close.)

    Fails closed: a supervisor with nothing to scope by gets a 403, never
    the whole country.
    """
    if user.role == "admin":
        return None

    from app.db.models.worker import Worker  # local import: circular at module load

    me = db.query(Worker).filter(Worker.worker_id == user.worker_id).first()
    if me is None:
        raise HTTPException(status_code=403, detail="Your account no longer exists")

    if user.role == "bmo":
        if not me.district_id or not me.district_id.strip():
            raise HTTPException(status_code=403, detail="BMO has no assigned district")
        rows = (
            db.query(Worker.sub_centre_id)
            .filter(Worker.district_id == me.district_id, Worker.sub_centre_id.isnot(None))
            .distinct()
        )
        return sorted({sub_centre_id for (sub_centre_id,) in rows})

    if not me.sub_centre_id or not me.sub_centre_id.strip():
        raise HTTPException(status_code=403, detail="No assigned sub-centre")
    return [me.sub_centre_id]


def require_worker_access(user: CurrentUser, db: Session, worker_id: str) -> None:
    """Guard worker-addressed reads without changing existing role policy."""
    if user.role == "asha":
        if worker_id != user.worker_id:
            raise HTTPException(status_code=403, detail="Not your worker record")
        return
    allowed = visible_sub_centres(user, db)
    if allowed is not None:
        from app.db.models.worker import Worker

        worker = db.get(Worker, worker_id)
        if worker is None or worker.sub_centre_id not in allowed:
            raise HTTPException(status_code=403, detail="Worker is outside your area")
