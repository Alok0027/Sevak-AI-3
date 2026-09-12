"""GET/POST /api/v1/admin/staff (district-wide staff directory + account
creation) and GET /api/v1/admin/audit-log (NFR-SC4 audit trail viewer).
Every route here is admin-only -- this is the panel an 'admin' role account
had nowhere to actually use before."""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import aliased

from app.api.deps import DbSession, require_roles
from app.core.security import hash_pin
from app.db.models.audit_log import AuditLog
from app.db.models.worker import Worker
from app.schemas.admin import (
    AuditLogEntry,
    AuditLogResponse,
    StaffCreateRequest,
    StaffListResponse,
    StaffMember,
)
from app.services.audit import record as audit_record

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# The audit log's user_id is sometimes a worker_id and sometimes (a failed
# login with an unrecognised phone) not a real worker at all -- outer join
# so those rows still show up, just without an actor name/role.
Actor = aliased(Worker)


@router.get("/staff", response_model=StaffListResponse)
def list_staff(
    db: DbSession,
    _user=Depends(require_roles("admin")),
    role: str | None = Query(default=None, description="Filter to one role: asha | anm | bmo | admin"),
) -> StaffListResponse:
    query = db.query(Worker)
    if role:
        query = query.filter(Worker.role == role.strip().lower())
    workers = query.order_by(Worker.role, Worker.name).all()
    return StaffListResponse(
        staff=[
            StaffMember(
                worker_id=w.worker_id,
                name=w.name,
                phone=w.phone,
                role=w.role,
                sub_centre_id=w.sub_centre_id,
                language_pref=w.language_pref,
                created_at=w.created_at,
            )
            for w in workers
        ]
    )


@router.post("/staff", response_model=StaffMember, status_code=201)
def create_staff(
    payload: StaffCreateRequest,
    db: DbSession,
    user=Depends(require_roles("admin")),
) -> StaffMember:
    if db.query(Worker).filter(Worker.phone == payload.phone).first() is not None:
        raise HTTPException(status_code=409, detail="A worker with this phone number already exists")

    worker = Worker(
        name=payload.name,
        phone=payload.phone,
        pin_hash=hash_pin(payload.pin),
        role=payload.role,
        sub_centre_id=payload.sub_centre_id,
        language_pref=payload.language_pref,
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)

    audit_record(
        db,
        user_id=user.worker_id,
        action_type="staff.create",
        record_id=worker.worker_id,
        record_type="worker",
        details={"name": worker.name, "role": worker.role, "sub_centre_id": worker.sub_centre_id},
    )
    return StaffMember(
        worker_id=worker.worker_id,
        name=worker.name,
        phone=worker.phone,
        role=worker.role,
        sub_centre_id=worker.sub_centre_id,
        language_pref=worker.language_pref,
        created_at=worker.created_at,
    )


@router.get("/audit-log", response_model=AuditLogResponse)
def list_audit_log(
    db: DbSession,
    _user=Depends(require_roles("admin")),
    action_type: str | None = Query(default=None, description="Exact match, e.g. 'risk.override'"),
    actor_search: str | None = Query(default=None, description="Case-insensitive substring match on actor name"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
) -> AuditLogResponse:
    query = db.query(AuditLog, Actor).outerjoin(Actor, Actor.worker_id == AuditLog.user_id)
    if action_type:
        query = query.filter(AuditLog.action_type == action_type)
    if date_from:
        query = query.filter(AuditLog.timestamp >= date_from)
    if date_to:
        query = query.filter(AuditLog.timestamp <= date_to)
    if actor_search:
        query = query.filter(Actor.name.ilike(f"%{actor_search}%"))
    rows = query.order_by(AuditLog.timestamp.desc()).limit(limit).all()

    return AuditLogResponse(
        entries=[
            AuditLogEntry(
                log_id=log.log_id,
                user_id=log.user_id,
                actor_name=actor.name if actor else None,
                actor_role=actor.role if actor else None,
                action_type=log.action_type,
                record_id=log.record_id,
                record_type=log.record_type,
                timestamp=log.timestamp,
                ip_address=log.ip_address,
                details=json.loads(log.details) if log.details else None,
            )
            for log, actor in rows
        ]
    )
