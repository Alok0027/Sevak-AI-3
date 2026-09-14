"""GET/POST /api/v1/admin/staff (district-wide staff directory + account
creation) and GET /api/v1/admin/audit-log (NFR-SC4 audit trail viewer).
Every route here is admin-only -- this is the panel an 'admin' role account
had nowhere to actually use before."""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import aliased

from app.api.deps import DbSession, require_roles
from app.core.security import hash_pin
from app.db.models.audit_log import AuditLog
from app.db.models.worker import Worker
from app.schemas.admin import (
    AuditLogEntry,
    AuditLogResponse,
    RegistrationDecisionRequest,
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


def _approver_names(db, workers: list[Worker]) -> dict[str, str]:
    """worker_id -> name, for whoever approved each of these accounts.

    One query rather than one per row: the staff list is the whole
    district, and an admin opening it should not pay a round trip per
    worker just to see who let each of them in.
    """
    ids = {w.approved_by for w in workers if w.approved_by}
    if not ids:
        return {}
    return {
        w.worker_id: w.name
        for w in db.query(Worker).filter(Worker.worker_id.in_(ids)).all()
    }


def _to_staff(w: Worker, approvers: dict[str, str]) -> StaffMember:
    return StaffMember(
        worker_id=w.worker_id,
        name=w.name,
        phone=w.phone,
        role=w.role,
        sub_centre_id=w.sub_centre_id,
        language_pref=w.language_pref,
        created_at=w.created_at,
        status=w.status,
        approved_by_name=approvers.get(w.approved_by) if w.approved_by else None,
        approved_at=w.approved_at,
    )


@router.get("/staff", response_model=StaffListResponse)
def list_staff(
    db: DbSession,
    _user=Depends(require_roles("admin")),
    role: str | None = Query(default=None, description="Filter to one role: asha | anm | bmo | admin"),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Filter to one state: pending | active | rejected",
    ),
) -> StaffListResponse:
    query = db.query(Worker)
    if role:
        query = query.filter(Worker.role == role.strip().lower())
    if status_filter:
        query = query.filter(Worker.status == status_filter.strip().lower())
    # Pending first. This list is where somebody waiting to start work is
    # either seen or forgotten; sorting by role would bury her among the
    # hundreds of people already working.
    workers = query.order_by(Worker.status.desc(), Worker.role, Worker.name).all()
    approvers = _approver_names(db, workers)
    return StaffListResponse(
        staff=[_to_staff(w, approvers) for w in workers],
        pending_count=db.query(Worker).filter(Worker.status == "pending").count(),
    )


@router.post("/staff/{worker_id}/approve", response_model=StaffMember)
def approve_registration(
    worker_id: str,
    db: DbSession,
    payload: RegistrationDecisionRequest | None = None,
    user=Depends(require_roles("admin")),
) -> StaffMember:
    """Let a registered worker in.

    This is the human check the whole registration flow exists for. The
    admin should have rung the number on the row before clicking. The
    system cannot verify that she did -- which is exactly why the decision
    is recorded against her name rather than happening on its own.
    """
    worker = db.query(Worker).filter(Worker.worker_id == worker_id).first()
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    if worker.status == "active":
        raise HTTPException(status_code=400, detail="This account is already active")

    worker.status = "active"
    worker.approved_by = user.worker_id
    worker.approved_at = datetime.now(timezone.utc)
    db.commit()

    audit_record(
        db,
        user_id=user.worker_id,
        action_type="staff.registration_approved",
        record_id=worker.worker_id,
        record_type="worker",
        details={
            "name": worker.name,
            "phone": worker.phone,
            "role": worker.role,
            "reason": payload.reason if payload else None,
        },
    )
    return _to_staff(worker, _approver_names(db, [worker]))


@router.post("/staff/{worker_id}/reject", response_model=StaffMember)
def reject_registration(
    worker_id: str,
    payload: RegistrationDecisionRequest,
    db: DbSession,
    user=Depends(require_roles("admin")),
) -> StaffMember:
    """Turn a registration down, with a reason.

    Rejected rather than deleted. The phone number stays claimed, so the
    same person re-registering does not simply queue up again as though
    nothing had happened; and an admin looking at the row next month can
    see a decision was made rather than wondering whether one was missed.
    """
    if not payload.reason or len(payload.reason.strip()) < 5:
        raise HTTPException(status_code=400, detail="Give a reason for the rejection")

    worker = db.query(Worker).filter(Worker.worker_id == worker_id).first()
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    if worker.role == "admin":
        raise HTTPException(status_code=400, detail="Admin accounts cannot be rejected here")
    if worker.status == "rejected":
        raise HTTPException(status_code=400, detail="This registration is already rejected")

    worker.status = "rejected"
    worker.approved_by = user.worker_id
    worker.approved_at = datetime.now(timezone.utc)
    db.commit()

    audit_record(
        db,
        user_id=user.worker_id,
        action_type="staff.registration_rejected",
        record_id=worker.worker_id,
        record_type="worker",
        details={"name": worker.name, "phone": worker.phone, "reason": payload.reason.strip()},
    )
    return _to_staff(worker, _approver_names(db, [worker]))


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
        # Active immediately, and said out loud rather than inherited from
        # the model default: an admin typing these details IS the approval
        # step. Making her create the account and then approve it would be
        # ceremony, and ceremony gets clicked through.
        status="active",
        approved_by=user.worker_id,
        approved_at=datetime.now(timezone.utc),
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
    return _to_staff(worker, _approver_names(db, [worker]))


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
