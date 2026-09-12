"""POST /api/v1/auth/login (SRS table 19)."""
from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import DbSession
from app.core.security import create_access_token, verify_pin
from app.db.models.worker import Worker
from app.schemas.auth import LoginRequest, LoginResponse
from app.services.audit import record as audit_record

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: DbSession, request: Request) -> LoginResponse:
    # NFR-SC4: audit trail for every data access -- logins included, with
    # the caller's IP so an admin reviewing the trail can spot a run of
    # failed attempts from somewhere unexpected.
    ip_address = request.client.host if request.client else None
    worker = db.query(Worker).filter(Worker.phone == payload.phone).first()
    if worker is None or not verify_pin(payload.pin, worker.pin_hash):
        audit_record(
            db,
            user_id=worker.worker_id if worker else payload.phone,
            action_type="auth.login_failed",
            record_type="worker",
            ip_address=ip_address,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid phone or PIN")

    token = create_access_token(subject=worker.worker_id, role=worker.role)
    audit_record(
        db,
        user_id=worker.worker_id,
        action_type="auth.login",
        record_id=worker.worker_id,
        record_type="worker",
        ip_address=ip_address,
    )
    return LoginResponse(
        access_token=token, role=worker.role, worker_id=worker.worker_id, worker_name=worker.name
    )
