"""GET /api/v1/workers (roster) + /api/v1/workers/{worker_id}/history.

Not in the SRS's original table 19 -- added to back the roster/drill-down
the ANM and BMO dashboards need (FR-08, table 4 'Worker performance
metrics'). Every field is a real aggregate over visits/patients/actions;
see app/services/worker_stats.py.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import aliased

from app.api.deps import DbSession, get_supervisor_scope, require_roles
from app.db.models.patient import Patient
from app.db.models.risk_flag import RiskFlag
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.schemas.worker import PatientHistoryEntry, WorkerHistoryResponse, WorkerRosterResponse
from app.services.audit import record as audit_record
from app.services.worker_stats import get_worker_stats, list_worker_stats

# Aliased because a visit's own worker (who did the visit) and the worker who
# overrode its risk level (who might be a different ASHA, or her ANM/BMO)
# are two different rows in the same table -- one join per role.
OverridingWorker = aliased(Worker)

router = APIRouter(prefix="/api/v1/workers", tags=["workers"])


@router.get("", response_model=WorkerRosterResponse)
def list_workers(
    db: DbSession,
    user=Depends(require_roles("anm", "bmo", "admin")),
    sub_centre_id: str | None = Query(default=None, description="BMO/Admin only: filter to one sub-centre"),
    search: str | None = Query(default=None, description="Filter by worker name (case-insensitive substring)"),
) -> WorkerRosterResponse:
    scope = get_supervisor_scope(user, db)
    # An ANM's scope always wins over any sub_centre_id they might pass.
    effective_sub_centre = scope or sub_centre_id
    stats = list_worker_stats(db, sub_centre_id=effective_sub_centre, search=search)
    return WorkerRosterResponse(workers=stats)


@router.get("/{worker_id}/history", response_model=WorkerHistoryResponse)
def worker_history(
    worker_id: str,
    db: DbSession,
    user=Depends(require_roles("asha", "anm", "bmo", "admin")),
) -> WorkerHistoryResponse:
    # An ASHA worker may only ever pull up her own history -- this doubles as
    # the mobile app's "my stats" home screen (patients treated, pending
    # follow-ups) as well as the ANM/BMO roster drill-down.
    if user.role == "asha" and worker_id != user.worker_id:
        raise HTTPException(status_code=403, detail="Not your worker record")

    scope = get_supervisor_scope(user, db)
    stats = get_worker_stats(db, worker_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    if scope and stats.sub_centre_id != scope:
        # ANM tried to reach another sub-centre's worker -- SRS table 4:
        # "Cannot access district-level data".
        raise HTTPException(status_code=403, detail="Worker is outside your sub-centre")

    rows = (
        db.query(Visit, Patient, RiskFlag, OverridingWorker)
        .join(Patient, Visit.patient_id == Patient.patient_id)
        .outerjoin(RiskFlag, RiskFlag.visit_id == Visit.visit_id)
        .outerjoin(OverridingWorker, OverridingWorker.worker_id == RiskFlag.overridden_by)
        .filter(Visit.worker_id == worker_id)
        .order_by(Visit.created_at.desc())
        .all()
    )
    visits = [
        PatientHistoryEntry(
            visit_id=v.visit_id,
            patient_id=p.patient_id,
            patient_name=p.name,
            created_at=v.created_at,
            risk_level=v.risk_level,
            transcript=v.transcript,
            extracted=json.loads(v.structured_json) if v.structured_json else None,
            risk_overridden=bool(rf and rf.overridden_by),
            risk_override_reason=rf.override_reason if rf else None,
            overridden_by_name=ow.name if ow else None,
            overridden_by_role=ow.role if ow else None,
        )
        for v, p, rf, ow in rows
    ]
    if user.worker_id != worker_id:
        # Only log this as a supervisor-accessed-someone-else's-record event
        # (NFR-SC4) -- an ASHA pulling her own "my stats" home screen isn't
        # a data-access event worth an audit row, and logging it would just
        # flood the trail with routine app usage every time she opens it.
        audit_record(
            db,
            user_id=user.worker_id,
            action_type="worker.view",
            record_id=worker_id,
            record_type="worker",
        )
    return WorkerHistoryResponse(worker=stats, visits=visits)
