"""POST /api/v1/auth/login (SRS table 19)."""
from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession
from app.core.security import create_access_token, verify_pin
from app.db.models.worker import Worker
from app.schemas.auth import LoginRequest, LoginResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: DbSession) -> LoginResponse:
    worker = db.query(Worker).filter(Worker.phone == payload.phone).first()
    if worker is None or not verify_pin(payload.pin, worker.pin_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid phone or PIN")

    token = create_access_token(subject=worker.worker_id, role=worker.role)
    return LoginResponse(
        access_token=token, role=worker.role, worker_id=worker.worker_id, worker_name=worker.name
    )
