"""GET /api/v1/workers (roster) + /api/v1/workers/{worker_id}/history.

Not in the SRS's original table 19 -- added to back the roster/drill-down
the ANM and BMO dashboards need (FR-08, table 4 'Worker performance
metrics'). Every field is a real aggregate over visits/patients/actions;
see app/services/worker_stats.py.
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import aliased

from app.api.deps import DbSession, get_supervisor_scope, require_roles
from app.db.models.absence import WorkerAbsence
from app.db.models.patient import Patient
from app.db.models.risk_flag import RiskFlag
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.schemas.worker import (
    AbsenceListResponse,
    AbsenceSummary,
    Colleague,
    DeclareAbsenceRequest,
    MyProfile,
    PatientHistoryEntry,
    WorkerHistoryResponse,
    WorkerRosterResponse,
)
from app.services import cover
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


def _absence_summary(db, absence, today=None) -> AbsenceSummary:
    today = today or datetime.now(timezone.utc).date()
    away = db.query(Worker).filter(Worker.worker_id == absence.worker_id).first()
    covering = db.query(Worker).filter(Worker.worker_id == absence.covering_worker_id).first()
    return AbsenceSummary(
        absence_id=absence.absence_id,
        worker_id=absence.worker_id,
        worker_name=away.name if away else "Unknown",
        worker_code=away.worker_code if away else None,
        covering_worker_id=absence.covering_worker_id,
        covering_worker_name=covering.name if covering else "Unknown",
        covering_worker_code=covering.worker_code if covering else None,
        starts_on=absence.starts_on,
        ends_on=absence.ends_on,
        reason=absence.reason,
        in_effect=absence.starts_on <= today <= absence.ends_on,
    )


@router.get("/me", response_model=MyProfile)
def my_profile(db: DbSession, user=Depends(require_roles("asha", "anm", "bmo", "admin"))) -> MyProfile:
    """Her own record.

    The worker code is the reason this exists. It is what she is asked for
    on a referral form and at a block meeting, and until now the only way
    to find it was to ask somebody with dashboard access -- which is an
    absurd thing to need for your own staff number.
    """
    me = db.query(Worker).filter(Worker.worker_id == user.worker_id).first()
    if me is None:
        raise HTTPException(status_code=401, detail="Your account no longer exists")

    patients = db.query(Patient).filter(Patient.worker_id == me.worker_id).count()
    visits = db.query(Visit).filter(Visit.worker_id == me.worker_id).count()

    mine = cover.upcoming_or_active_absence(db, me.worker_id)
    return MyProfile(
        worker_id=me.worker_id,
        worker_code=me.worker_code,
        name=me.name,
        phone=me.phone,
        role=me.role,
        sub_centre_id=me.sub_centre_id,
        language_pref=me.language_pref,
        joined_on=me.created_at,
        total_patients=patients,
        total_visits=visits,
        my_absence=_absence_summary(db, mine) if mine else None,
        covering_for=[
            _absence_summary(db, a) for a in cover.active_absences_for(db, me.worker_id)
        ],
    )


@router.get("/colleagues", response_model=list[Colleague])
def my_colleagues(db: DbSession, user=Depends(require_roles("asha", "anm"))) -> list[Colleague]:
    """The other ASHAs in her sub-centre -- the list of people who could
    cover for her.

    Names and codes only. She needs to pick somebody, not to be handed a
    staff directory: phone numbers and account states are her supervisor's
    business, not a peer's.
    """
    me = db.query(Worker).filter(Worker.worker_id == user.worker_id).first()
    if me is None or not me.sub_centre_id:
        return []
    others = (
        db.query(Worker)
        .filter(
            Worker.role == "asha",
            Worker.sub_centre_id == me.sub_centre_id,
            Worker.status == "active",
            Worker.worker_id != me.worker_id,
        )
        .order_by(Worker.name)
        .all()
    )
    return [Colleague(worker_id=w.worker_id, worker_code=w.worker_code, name=w.name) for w in others]


@router.post("/me/absence", response_model=AbsenceSummary, status_code=201)
def declare_absence(
    payload: DeclareAbsenceRequest,
    db: DbSession,
    user=Depends(require_roles("asha")),
) -> AbsenceSummary:
    """"I am away until the 20th, and Kavita is covering."

    She arranges this herself, and that is the point. Requiring a
    supervisor to approve a fortnight's leave means an ASHA leaving on
    Friday needs her ANM at a desk on Friday, and the reliable outcome of
    that is she tells a colleague verbally and the system never hears
    about it -- which is exactly what happens today.

    It is safe to let her because nothing is given away. Ownership does
    not move (that is POST /patients/caseload/{id}/reassign, and it needs
    an ANM); the colleague gains sight and the ability to record, for a
    stated window, and it lapses on its own. Her ANM sees it either way.
    """
    me = db.query(Worker).filter(Worker.worker_id == user.worker_id).first()
    if me is None:
        raise HTTPException(status_code=401, detail="Your account no longer exists")

    if payload.ends_on < payload.starts_on:
        raise HTTPException(status_code=400, detail="The last day is before the first day")
    if payload.covering_worker_id == me.worker_id:
        raise HTTPException(status_code=400, detail="You cannot cover for yourself")

    covering = db.query(Worker).filter(Worker.worker_id == payload.covering_worker_id).first()
    if (
        covering is None
        or covering.role != "asha"
        or covering.status != "active"
        or covering.sub_centre_id != me.sub_centre_id
    ):
        raise HTTPException(status_code=400, detail="Pick an active ASHA in your own sub-centre")

    # One at a time. Two overlapping covers would mean two people each
    # believing the other is not responsible, which is worse than nobody
    # covering at all -- at least then she knows.
    existing = cover.upcoming_or_active_absence(db, me.worker_id)
    if existing is not None and existing.starts_on <= payload.ends_on and payload.starts_on <= existing.ends_on:
        raise HTTPException(
            status_code=409,
            detail="You already have leave booked over those dates. End it first.",
        )

    absence = WorkerAbsence(
        worker_id=me.worker_id,
        covering_worker_id=covering.worker_id,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        reason=payload.reason.strip() if payload.reason else None,
        created_by=me.worker_id,
    )
    db.add(absence)
    db.commit()
    db.refresh(absence)

    audit_record(
        db,
        user_id=me.worker_id,
        action_type="worker.absence_declared",
        record_id=absence.absence_id,
        record_type="worker_absence",
        details={
            "covering_worker_id": covering.worker_id,
            "covering_worker_name": covering.name,
            "starts_on": str(payload.starts_on),
            "ends_on": str(payload.ends_on),
            "reason": absence.reason,
        },
    )
    return _absence_summary(db, absence)


@router.delete("/me/absence/{absence_id}", response_model=AbsenceSummary)
def end_absence(
    absence_id: str,
    db: DbSession,
    user=Depends(require_roles("asha")),
) -> AbsenceSummary:
    """She is back early, or booked it by mistake.

    The row is ended, not deleted. Who covered which village in March is a
    fact somebody may want in April, and a deleted row answers nothing.
    """
    absence = db.query(WorkerAbsence).filter(WorkerAbsence.absence_id == absence_id).first()
    if absence is None or absence.worker_id != user.worker_id:
        # Same answer for "no such absence" and "not yours", so the
        # endpoint cannot be used to probe other people's leave.
        raise HTTPException(status_code=404, detail="No such leave record")
    if absence.ended_at is not None:
        raise HTTPException(status_code=400, detail="That leave has already ended")

    absence.ended_at = datetime.now(timezone.utc)
    db.commit()

    audit_record(
        db,
        user_id=user.worker_id,
        action_type="worker.absence_ended",
        record_id=absence_id,
        record_type="worker_absence",
    )
    return _absence_summary(db, absence)


@router.get("/absences", response_model=AbsenceListResponse)
def list_absences(
    db: DbSession,
    user=Depends(require_roles("anm", "bmo", "admin")),
) -> AbsenceListResponse:
    """Who is away in this sub-centre, and who is carrying their patients.

    A supervisor finding out that half her block arranged cover between
    themselves and never told her is the failure this replaces.
    """
    today = datetime.now(timezone.utc).date()
    query = (
        db.query(WorkerAbsence)
        .filter(WorkerAbsence.ends_on >= today, WorkerAbsence.ended_at.is_(None))
        .order_by(WorkerAbsence.starts_on)
    )
    scope = get_supervisor_scope(user, db)
    absences = query.all()
    if scope:
        in_scope = {
            w.worker_id
            for w in db.query(Worker).filter(Worker.sub_centre_id == scope).all()
        }
        absences = [a for a in absences if a.worker_id in in_scope]
    return AbsenceListResponse(absences=[_absence_summary(db, a, today) for a in absences])
