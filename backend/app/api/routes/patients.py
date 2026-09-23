"""GET /api/v1/patients/{worker_id} (FR-07.2: patient list with risk badges)
and GET /api/v1/patients/{patient_id}/history (full visit timeline).

Both list endpoints return patients in triage order rather than whatever
the database hands back -- see app/services/patient_priority.py for why
order carries more of the signal here than colour does.
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import aliased

from app.api.deps import (
    DbSession,
    get_supervisor_scope,
    require_roles,
    require_worker_access,
    visible_sub_centres,
)
from app.core.config import get_settings
from app.db.models.action import Action
from app.db.models.patient import Patient
from app.db.models.risk_flag import RiskFlag
from app.db.models.risk_resolution import RiskResolution
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.schemas.patient import (
    PatientCreate,
    PatientDirectoryEntry,
    PatientDirectoryResponse,
    PatientListResponse,
    PatientStatusChange,
    PatientStatusResult,
    PatientSummary,
    PatientUpdate,
    PatientVoiceIntakeRequest,
    PatientVoiceIntakeResponse,
    ReassignRequest,
    ReassignResult,
)
from app.schemas.worker import PatientHistoryEntry, PatientHistoryResponse
from app.services import cover, identity, patient_intake, patient_priority
from app.services.llm_client import get_llm_client
from app.services.audit import record as audit_record
from app.services.audit import record_read as audit_read
from app.services.bhashini_client import get_bhashini_client

# Aliased because a patient's assigned worker and the worker who overrode a
# visit's risk level (could be a different ASHA, or her ANM/BMO) are two
# different rows in the same table.
OverridingWorker = aliased(Worker)
ResolvingWorker = aliased(Worker)

router = APIRouter(prefix="/api/v1/patients", tags=["patients"])


def _open_followups(db, patient_ids: list[str]) -> dict[str, tuple[int, datetime | None]]:
    """patient_id -> (how many follow-ups are still open, the earliest deadline).

    Earliest, not latest. A mother with one follow-up two days late and
    another due next week is two days late; taking the later date would
    quietly retire the lapse, which is the one thing this whole ranking
    exists to surface.

    One grouped query rather than one per patient: an ANM's district view
    is several hundred rows, and a per-row round trip would make opening
    the page slower than the thing it is trying to save her.
    """
    if not patient_ids:
        return {}
    rows = (
        db.query(
            Visit.patient_id,
            func.count(Action.action_id),
            func.min(Action.due_at),
        )
        .join(Action, Action.visit_id == Visit.visit_id)
        .filter(
            Visit.patient_id.in_(patient_ids),
            Action.type == "followup",
            # The same definition of "still owed" the task board uses
            # (routes/tasks.py). A done or cancelled follow-up is not a
            # debt, however late its date has since become.
            Action.status == "pending",
        )
        .group_by(Visit.patient_id)
        .all()
    )
    return {patient_id: (count, earliest) for patient_id, count, earliest in rows}


@router.post("/voice-intake", response_model=PatientVoiceIntakeResponse)
async def voice_intake(
    payload: PatientVoiceIntakeRequest,
    _user=Depends(require_roles("asha")),
) -> PatientVoiceIntakeResponse:
    """FR-07.2 voice-fill: transcribe a spoken patient description and pull
    out name/age/gender/village/phone so the Add Patient form can be
    pre-filled. Read-only -- creates nothing; the ASHA reviews the
    pre-filled form and taps Save herself via POST /api/v1/patients."""
    settings = get_settings()
    stt_client = get_bhashini_client(settings)
    transcript = await stt_client.transcribe(payload.audio_base64, payload.language_code)
    # Parser first, model only for what it could not read -- see
    # patient_intake.extract_with_llm. Registration stays usable offline.
    extracted = await patient_intake.extract_with_llm(transcript, get_llm_client(settings))
    return PatientVoiceIntakeResponse(transcript=transcript, extracted=extracted)


@router.post("", response_model=PatientSummary, status_code=201)
def create_patient(
    payload: PatientCreate,
    db: DbSession,
    user=Depends(require_roles("asha", "anm")),
) -> PatientSummary:
    """FR-07.2 prerequisite: register a new patient.

    An ASHA registers her own, which is the field case and by far the
    common one. An ANM may also register one *to* a named ASHA in her
    sub-centre, by passing worker_id -- that is the only way anything ever
    flowed downward in this system. In real life the ANM holds the
    sub-centre's RCH register and hands the line-list to her workers;
    before this, the ANM could only watch.
    """
    owner = _resolve_owner(db, user, payload.worker_id)
    rch = _validated_rch(payload.rch_number)
    village = payload.village.strip() if payload.village else None
    phone_hash = identity.phone_index(payload.phone)

    _reject_duplicates(db, rch=rch, phone_hash=phone_hash, sub_centre_id=owner.sub_centre_id)

    patient = Patient(
        worker_id=owner.worker_id,
        name=payload.name.strip(),
        age=payload.age,
        gender=payload.gender,
        village=village,
        village_code=identity.village_code(village),
        # Hers from here on, and left alone when her caseload moves: she
        # has not changed village because her ASHA changed jobs.
        sub_centre_id=owner.sub_centre_id,
        phone=payload.phone,
        phone_hash=phone_hash,
        rch_number=rch,
        pregnancy_stage=payload.pregnancy_stage,
        bp_systolic=payload.bp_systolic,
        bp_diastolic=payload.bp_diastolic,
        blood_sugar_fasting=payload.blood_sugar_fasting,
        blood_sugar_random=payload.blood_sugar_random,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)

    audit_record(
        db,
        user_id=user.worker_id,
        action_type="patient.create",
        record_id=patient.patient_id,
        record_type="patient",
        details={"assigned_to": owner.worker_id, "by_role": user.role},
    )
    return PatientSummary(
        id=patient.patient_id,
        name=patient.name,
        age=patient.age,
        village=patient.village,
        pregnancy_stage=patient.pregnancy_stage,
        rch_number=patient.rch_number,
        risk_status=None,
        last_visit=None,
        total_visits=0,
    )


def _resolve_owner(db, user, requested_worker_id: str | None) -> Worker:
    """Which ASHA this patient belongs to.

    An ASHA registers for herself and may not name somebody else: a
    worker who could file patients onto a colleague's list could also
    quietly empty her own.
    """
    get_supervisor_scope(user, db)  # fail closed for an unassigned ANM
    me = db.query(Worker).filter(Worker.worker_id == user.worker_id).first()
    if me is None:
        raise HTTPException(status_code=401, detail="Your account no longer exists")

    if requested_worker_id is None or requested_worker_id == user.worker_id:
        if user.role == "anm":
            raise HTTPException(
                status_code=400,
                detail="Name the ASHA this patient belongs to",
            )
        return me

    if user.role != "anm":
        raise HTTPException(status_code=403, detail="You can only register your own patients")

    owner = db.query(Worker).filter(Worker.worker_id == requested_worker_id).first()
    if owner is None or owner.role != "asha" or owner.sub_centre_id != me.sub_centre_id:
        # One message for "no such worker" and "not one of yours", so the
        # endpoint cannot be used to discover which workers exist.
        raise HTTPException(status_code=403, detail="That worker is not an ASHA in your sub-centre")
    return owner


def _validated_rch(value: str | None) -> str | None:
    try:
        return identity.normalise_rch(value)
    except identity.InvalidRchNumber as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _reject_duplicates(db, *, rch: str | None, phone_hash: str | None, sub_centre_id: str | None) -> None:
    """Refuse to register the same woman twice.

    Two checks, deliberately different in reach.

    The RCH number is issued by the health system and is unique across
    the country, so a match anywhere is the same person -- even in another
    district.

    A phone number is not an identity. Households share one, a number gets
    reissued, a daughter uses her mother's. Matching on it across a whole
    district would block real registrations; matching within a sub-centre
    catches the case that actually happens -- two ASHAs in neighbouring
    hamlets registering the same pregnant woman -- and no more.

    Both refuse rather than merge. Merging two patient records is a
    clinical decision with a history attached, and it is not one an
    endpoint should make on somebody's behalf at a doorstep.
    """
    if rch:
        clash = db.query(Patient).filter(Patient.rch_number == rch).first()
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail="That RCH number is already registered. Check the MCP card.",
            )
    if phone_hash and sub_centre_id:
        clash = (
            db.query(Patient)
            .filter(Patient.phone_hash == phone_hash, Patient.sub_centre_id == sub_centre_id)
            .first()
        )
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail="Somebody with this phone number is already registered in this sub-centre.",
            )


@router.get("", response_model=PatientDirectoryResponse)
def list_all_patients(
    db: DbSession,
    # No "admin" here, deliberately. SRS table 4 gives the Admin role
    # worker onboarding, protocol configuration and user management, and
    # *no patient record access* -- the role administers the system, not
    # the care. It kept that access for a long time because the role list
    # was written once and copied to each new endpoint; a system
    # administrator who can read every pregnant woman's clinical history
    # in the state is a standing DPDP exposure with no operational reason
    # behind it.
    #
    # What an admin keeps: the aggregate dashboard (counts and village
    # totals, no identities), the worker roster, caseload reassignment
    # (which returns counts and worker names only), and the audit log.
    user=Depends(require_roles("anm", "bmo")),
    sub_centre_id: str | None = Query(default=None, description="BMO only: filter to one sub-centre"),
) -> PatientDirectoryResponse:
    """FR-08 drill-down: 'which patients are my ASHA workers actually
    treating right now' -- every patient across the ANM's own sub-centre,
    or (BMO) the whole district, in one place. The per-worker
    GET /patients/{worker_id} above can't answer that; it only ever shows
    one ASHA's patients at a time, so a supervisor would have to open every
    worker one by one to see who's being treated. The dashboard's Patients
    page filters this list client-side (gender, risk level, registration
    date, name search) -- this endpoint just returns the properly-scoped
    set for it to filter."""
    allowed = visible_sub_centres(user, db)

    rows = (
        db.query(Patient, Worker)
        .join(Worker, Patient.worker_id == Worker.worker_id)
        # A closed line is not a caseload entry any more. Her visits stay
        # in every historical figure -- what she leaves is the list of
        # people someone is expected to go and see.
        .filter(Worker.role == "asha", Patient.status == "active")
    )
    if allowed is not None:
        rows = rows.filter(Worker.sub_centre_id.in_(allowed))
    # A caller may narrow further, never widen: the requested sub-centre
    # is intersected with what they may see, not substituted for it.
    if sub_centre_id and (allowed is None or sub_centre_id in allowed):
        rows = rows.filter(Worker.sub_centre_id == sub_centre_id)
    elif sub_centre_id:
        raise HTTPException(status_code=403, detail="That sub-centre is outside your area")
    rows = rows.order_by(Patient.created_at.desc()).all()

    patient_ids = [p.patient_id for p, _ in rows]
    visit_counts: dict[str, int] = {}
    last_visit_by_patient: dict[str, Visit] = {}
    if patient_ids:
        visit_counts = dict(
            db.query(Visit.patient_id, func.count(Visit.visit_id))
            .filter(Visit.patient_id.in_(patient_ids))
            .group_by(Visit.patient_id)
            .all()
        )
        # Newest-first per patient, first one seen wins -- a simple,
        # dialect-portable way to get "last visit" without a
        # database-specific greatest-n-per-group query.
        for v in (
            db.query(Visit)
            .filter(Visit.patient_id.in_(patient_ids))
            .order_by(Visit.created_at.desc())
            .all()
        ):
            last_visit_by_patient.setdefault(v.patient_id, v)

    followups = _open_followups(db, patient_ids)

    def _entry(p: Patient, w: Worker) -> PatientDirectoryEntry:
        last = last_visit_by_patient.get(p.patient_id)
        open_count, next_due = followups.get(p.patient_id, (0, None))
        priority = patient_priority.assess(
            last.risk_level if last else None, next_due, has_open_followup=open_count > 0
        )
        return PatientDirectoryEntry(
            id=p.patient_id,
            name=p.name,
            age=p.age,
            gender=p.gender,
            village=p.village,
            pregnancy_stage=p.pregnancy_stage,
            risk_status=last.risk_level if last else None,
            last_visit=last.created_at if last else None,
            total_visits=visit_counts.get(p.patient_id, 0),
            registered_at=p.created_at,
            worker_id=w.worker_id,
            worker_name=w.name,
            sub_centre_id=w.sub_centre_id,
            priority_score=priority.score,
            needs_attention=priority.needs_attention,
            attention_reason=priority.reason,
            hours_overdue=priority.hours_overdue,
            open_followups=open_count,
            next_followup_due=next_due,
        )

    entries = [_entry(p, w) for p, w in rows]
    # Same order the ASHA sees. The page is sortable by every column, so
    # this is only the default -- but a default is what a supervisor
    # opening the page at 9am actually reads, and "newest registration
    # first" answered a question nobody was asking.
    entries.sort(key=lambda e: (-e.priority_score, e.name.lower()))
    audit_record(
        db,
        user_id=user.worker_id,
        action_type="patient.directory_view",
        record_type="patient",
        # What was actually read, not what was asked for: the audit trail
        # should show the scope the query ran under (NFR-SC4).
        details={
            "sub_centre_id": sub_centre_id,
            "scoped_to": allowed,
            "result_count": len(entries),
        },
    )
    return PatientDirectoryResponse(
        patients=entries,
        attention_count=sum(1 for e in entries if e.needs_attention),
    )


@router.get("/{worker_id}", response_model=PatientListResponse)
def list_patients(
    worker_id: str,
    db: DbSession,
    # No "admin" here, deliberately. SRS table 4 gives the Admin role
    # worker onboarding, protocol configuration and user management, and
    # *no patient record access* -- the role administers the system, not
    # the care. It kept that access for a long time because the role list
    # was written once and copied to each new endpoint; a system
    # administrator who can read every pregnant woman's clinical history
    # in the state is a standing DPDP exposure with no operational reason
    # behind it.
    #
    # What an admin keeps: the aggregate dashboard (counts and village
    # totals, no identities), the worker roster, caseload reassignment
    # (which returns counts and worker names only), and the audit log.
    user=Depends(require_roles("asha", "anm", "bmo")),
) -> PatientListResponse:
    require_worker_access(user, db, worker_id)
    # Her own patients, plus anyone she is standing in for today.
    #
    # Cover is the reason this is not a single equality any more. An ASHA
    # away for a fortnight names a colleague (POST /workers/me/absence);
    # while that window is open her patients appear on the colleague's
    # list, marked, without ever ceasing to be hers.
    visible = cover.visible_worker_ids(db, worker_id)
    covering_names = (
        {
            w.worker_id: w.name
            for w in db.query(Worker).filter(Worker.worker_id.in_(visible[1:])).all()
        }
        if len(visible) > 1
        else {}
    )

    patients = (
        db.query(Patient)
        .filter(Patient.worker_id.in_(visible), Patient.status == "active")
        .all()
    )
    visit_counts = dict(
        db.query(Visit.patient_id, func.count(Visit.visit_id))
        .filter(Visit.patient_id.in_([p.patient_id for p in patients]))
        .group_by(Visit.patient_id)
        .all()
    ) if patients else {}

    followups = _open_followups(db, [p.patient_id for p in patients])

    summaries = []
    for p in patients:
        last_visit = (
            db.query(Visit)
            .filter(Visit.patient_id == p.patient_id)
            .order_by(Visit.created_at.desc())
            .first()
        )
        risk = last_visit.risk_level if last_visit else None
        open_count, next_due = followups.get(p.patient_id, (0, None))
        priority = patient_priority.assess(
            risk, next_due, has_open_followup=open_count > 0
        )
        summaries.append(
            PatientSummary(
                id=p.patient_id,
                name=p.name,
                age=p.age,
                village=p.village,
                pregnancy_stage=p.pregnancy_stage,
                risk_status=risk,
                last_visit=last_visit.created_at if last_visit else None,
                total_visits=visit_counts.get(p.patient_id, 0),
                priority_score=priority.score,
                needs_attention=priority.needs_attention,
                attention_reason=priority.reason,
                hours_overdue=priority.hours_overdue,
                open_followups=open_count,
                next_followup_due=next_due,
                # Named, not just flagged. "Covering for Sunita" tells her
                # whose patient this is and who to hand the story back to;
                # a bare badge would leave her guessing at the doorstep.
                covering_for=covering_names.get(p.worker_id),
            )
        )

    # Worst first, then longest-waiting. The name tiebreak is not cosmetic:
    # without it two patients on the same score can swap places between
    # refreshes, and a list that reorders under an ASHA's thumb is a list
    # she stops trusting.
    summaries.sort(key=lambda s: (-s.priority_score, s.name.lower()))
    audit_read(db, user.worker_id, worker_id, "patient", count=len(summaries))
    return PatientListResponse(
        patients=summaries,
        attention_count=sum(1 for s in summaries if s.needs_attention),
    )


@router.get("/{patient_id}/history", response_model=PatientHistoryResponse)
def patient_history(
    patient_id: str,
    db: DbSession,
    # No "admin" here, deliberately. SRS table 4 gives the Admin role
    # worker onboarding, protocol configuration and user management, and
    # *no patient record access* -- the role administers the system, not
    # the care. It kept that access for a long time because the role list
    # was written once and copied to each new endpoint; a system
    # administrator who can read every pregnant woman's clinical history
    # in the state is a standing DPDP exposure with no operational reason
    # behind it.
    #
    # What an admin keeps: the aggregate dashboard (counts and village
    # totals, no identities), the worker roster, caseload reassignment
    # (which returns counts and worker names only), and the audit log.
    user=Depends(require_roles("asha", "anm", "bmo")),
) -> PatientHistoryResponse:
    patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    worker = db.query(Worker).filter(Worker.worker_id == patient.worker_id).first()

    if user.role == "asha" and patient.worker_id not in cover.visible_worker_ids(db, user.worker_id):
        raise HTTPException(status_code=403, detail="Not your patient")
    allowed = visible_sub_centres(user, db)
    if allowed is not None and (worker is None or worker.sub_centre_id not in allowed):
        raise HTTPException(status_code=403, detail="Patient is outside your area")

    rows = (
        db.query(Visit, RiskFlag, OverridingWorker, RiskResolution, ResolvingWorker)
        .outerjoin(RiskFlag, RiskFlag.visit_id == Visit.visit_id)
        .outerjoin(OverridingWorker, OverridingWorker.worker_id == RiskFlag.overridden_by)
        .outerjoin(RiskResolution, RiskResolution.visit_id == Visit.visit_id)
        .outerjoin(ResolvingWorker, ResolvingWorker.worker_id == RiskResolution.resolved_by)
        .filter(Visit.patient_id == patient_id)
        .order_by(Visit.created_at.desc())
        .all()
    )
    visits = [
        PatientHistoryEntry(
            visit_id=v.visit_id,
            patient_id=patient_id,
            patient_name=patient.name,
            created_at=v.created_at,
            risk_level=v.risk_level,
            transcript=v.transcript,
            extracted=json.loads(v.structured_json) if v.structured_json else None,
            risk_overridden=bool(rf and rf.overridden_by),
            risk_override_reason=rf.override_reason if rf else None,
            overridden_by_name=ow.name if ow else None,
            overridden_by_role=ow.role if ow else None,
            risk_resolved=res is not None,
            risk_resolution_note=res.note if res else None,
            resolved_by_name=resw.name if resw else None,
            resolved_at=res.resolved_at if res else None,
        )
        for v, rf, ow, res, resw in rows
    ]
    audit_record(
        db,
        user_id=user.worker_id,
        action_type="patient.view",
        record_id=patient_id,
        record_type="patient",
    )
    return PatientHistoryResponse(
        patient_id=patient_id,
        patient_name=patient.name,
        worker_id=patient.worker_id,
        worker_name=worker.name if worker else "Unknown",
        village=patient.village,
        age=patient.age,
        gender=patient.gender,
        phone=patient.phone,
        pregnancy_stage=patient.pregnancy_stage,
        bp_systolic=patient.bp_systolic,
        bp_diastolic=patient.bp_diastolic,
        blood_sugar_fasting=patient.blood_sugar_fasting,
        blood_sugar_random=patient.blood_sugar_random,
        registered_at=patient.created_at,
        visits=visits,
    )


def _reassign_guard(db, user, target_worker_id: str) -> tuple[Worker, Worker]:
    """(me, the ASHA receiving the caseload), or a refusal.

    An ANM moves patients within her own sub-centre and nowhere else. She
    is the person who knows that Sunita has left and that Kavita now walks
    those streets; she is not the person who should be able to move a
    caseload into the next block.
    """
    get_supervisor_scope(user, db)
    me = db.query(Worker).filter(Worker.worker_id == user.worker_id).first()
    if me is None:
        raise HTTPException(status_code=401, detail="Your account no longer exists")

    to_worker = db.query(Worker).filter(Worker.worker_id == target_worker_id).first()
    if to_worker is None or to_worker.role != "asha":
        raise HTTPException(status_code=404, detail="No such ASHA worker")
    if to_worker.status != "active":
        # Handing a caseload to an account that cannot log in is the same
        # as losing it, and it would look like it worked.
        raise HTTPException(status_code=400, detail="That worker's account is not active")
    if user.role != "admin" and to_worker.sub_centre_id != me.sub_centre_id:
        raise HTTPException(status_code=403, detail="That worker is outside your sub-centre")
    return me, to_worker


@router.post("/{patient_id}/reassign", response_model=ReassignResult)
def reassign_patient(
    patient_id: str,
    payload: ReassignRequest,
    db: DbSession,
    user=Depends(require_roles("anm", "admin")),
) -> ReassignResult:
    """Move one patient to another ASHA."""
    patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    me, to_worker = _reassign_guard(db, user, payload.to_worker_id)
    if user.role != "admin":
        current = db.query(Worker).filter(Worker.worker_id == patient.worker_id).first()
        if current is None or current.sub_centre_id != me.sub_centre_id:
            raise HTTPException(status_code=403, detail="That patient is outside your sub-centre")
    if patient.worker_id == to_worker.worker_id:
        raise HTTPException(status_code=400, detail="She is already with that worker")

    previous = patient.worker_id
    patient.worker_id = to_worker.worker_id
    # sub_centre_id is deliberately untouched. The patient belongs to a
    # place; only her carer changed.
    db.commit()

    audit_record(
        db,
        user_id=user.worker_id,
        action_type="patient.reassign",
        record_id=patient_id,
        record_type="patient",
        details={
            "from_worker_id": previous,
            "to_worker_id": to_worker.worker_id,
            "reason": payload.reason.strip(),
        },
    )
    return ReassignResult(
        moved=1,
        from_worker_id=previous,
        to_worker_id=to_worker.worker_id,
        to_worker_name=to_worker.name,
    )


@router.post("/caseload/{from_worker_id}/reassign", response_model=ReassignResult)
def reassign_caseload(
    from_worker_id: str,
    payload: ReassignRequest,
    db: DbSession,
    user=Depends(require_roles("anm", "admin")),
) -> ReassignResult:
    """Move a whole caseload from one ASHA to another.

    This is the gap that mattered. ASHAs leave, go on maternity leave, and
    are replaced, and until now their patients simply became unreachable:
    GET /patients/{worker_id} filters by worker_id, so nobody else could
    see them and no visit could be recorded against them. A supervisor
    could still read the names on her dashboard and could do nothing about
    any of them.

    In real life the register is physically handed to the next woman. This
    is that, with a note saying why.
    """
    me, to_worker = _reassign_guard(db, user, payload.to_worker_id)
    if from_worker_id == payload.to_worker_id:
        raise HTTPException(status_code=400, detail="Those are the same worker")

    from_worker = db.query(Worker).filter(Worker.worker_id == from_worker_id).first()
    if from_worker is None:
        raise HTTPException(status_code=404, detail="No such worker")
    if user.role != "admin" and from_worker.sub_centre_id != me.sub_centre_id:
        raise HTTPException(status_code=403, detail="That worker is outside your sub-centre")

    patients = (
        db.query(Patient)
        .filter(Patient.worker_id == from_worker_id, Patient.status == "active")
        .all()
    )
    for patient in patients:
        patient.worker_id = to_worker.worker_id
    db.commit()

    # One entry for the decision, not one per patient. A handover is a
    # single act by a single person, and forty rows saying the same thing
    # would bury the forty other things that happened that day.
    audit_record(
        db,
        user_id=user.worker_id,
        action_type="patient.reassign_caseload",
        record_id=from_worker_id,
        record_type="worker",
        details={
            "from_worker_id": from_worker_id,
            "from_worker_name": from_worker.name,
            "to_worker_id": to_worker.worker_id,
            "to_worker_name": to_worker.name,
            "patients_moved": len(patients),
            "reason": payload.reason.strip(),
        },
    )
    return ReassignResult(
        moved=len(patients),
        from_worker_id=from_worker_id,
        to_worker_id=to_worker.worker_id,
        to_worker_name=to_worker.name,
    )


def _writable_patient(db, user, patient_id: str) -> Patient:
    """The patient, if this caller may correct her record.

    Deliberately narrower than who may *read* it. An ASHA may correct her
    own patients (including anyone she is covering for), and an ANM may
    correct anyone in her sub-centre, because those two are the people
    who actually meet the woman and can check the spelling of her name.

    A BMO may not, even though she can read every record in the district:
    SRS table 4 gives her "read-only access to patient data", and a
    district officer editing a demographic detail she has no way to verify
    is not a correction, it is a guess overwriting the only person who
    knows. Admin may not either, for the same reason plus the one in
    deps.visible_sub_centres -- the admin role administers the system, not
    a place.
    """
    patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    if user.role == "asha":
        if patient.worker_id not in cover.visible_worker_ids(db, user.worker_id):
            raise HTTPException(status_code=403, detail="Not your patient")
        return patient

    # ANM: her own sub-centre only.
    allowed = visible_sub_centres(user, db)
    if allowed is not None and patient.sub_centre_id not in allowed:
        raise HTTPException(status_code=403, detail="Patient is outside your area")
    return patient


@router.patch("/{patient_id}", response_model=PatientSummary)
def correct_patient(
    patient_id: str,
    payload: PatientUpdate,
    db: DbSession,
    user=Depends(require_roles("asha", "anm")),
) -> PatientSummary:
    """Correct a registered patient's details.

    Only the fields actually present in the request body are written --
    `exclude_unset`, not `exclude_none` -- so a client that knows about an
    age and nothing else cannot blank the phone number it never sent.

    The audit entry records the old and new value of every field that
    changed, which is the point of the endpoint as much as the correction
    is: "her name used to be something else" is exactly the kind of edit
    that has to be reconstructable later.
    """
    patient = _writable_patient(db, user, patient_id)

    fields = payload.model_dump(exclude_unset=True, exclude={"reason", "clear_pregnancy_stage"})
    changes: dict[str, dict] = {}

    for field, new_value in fields.items():
        if new_value is None:
            continue  # "not sent" and "sent as null" both mean leave alone
        old_value = getattr(patient, field)
        if old_value == new_value:
            continue
        setattr(patient, field, new_value)
        # The audit log is readable by anyone with the admin console, so it
        # records that a field changed and not what it changed to for the
        # two fields that are encrypted at rest. Logging the old name in
        # clear would undo the encryption on the row it describes.
        if field in ("name", "phone"):
            changes[field] = {"changed": True}
        else:
            changes[field] = {"from": old_value, "to": new_value}

    if payload.clear_pregnancy_stage and patient.pregnancy_stage is not None:
        changes["pregnancy_stage"] = {"from": patient.pregnancy_stage, "to": None}
        patient.pregnancy_stage = None

    # Keep the derived lookup keys in step with the values they index, or
    # a corrected village stops matching the heatmap's grouping and a
    # corrected phone stops matching the duplicate check.
    if "village" in changes:
        patient.village_code = identity.village_code(patient.village)
    if "phone" in changes:
        patient.phone_hash = identity.phone_index(patient.phone)

    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to correct -- no field differs")

    db.commit()
    db.refresh(patient)

    audit_record(
        db,
        user_id=user.worker_id,
        action_type="patient.correct",
        record_id=patient_id,
        record_type="patient",
        details={"reason": payload.reason, "changed": changes, "by_role": user.role},
    )

    visits = db.query(Visit).filter(Visit.patient_id == patient_id).order_by(Visit.created_at.desc()).all()
    return PatientSummary(
        id=patient.patient_id,
        name=patient.name,
        age=patient.age,
        village=patient.village,
        pregnancy_stage=patient.pregnancy_stage,
        rch_number=patient.rch_number,
        risk_status=visits[0].risk_level if visits else None,
        last_visit=visits[0].created_at if visits else None,
        total_visits=len(visits),
    )


@router.post("/{patient_id}/status", response_model=PatientStatusResult)
def change_patient_status(
    patient_id: str,
    payload: PatientStatusChange,
    db: DbSession,
    user=Depends(require_roles("asha", "anm")),
) -> PatientStatusResult:
    """Close a patient's line in the register, or reopen one closed by mistake.

    Closing cancels her pending follow-up tasks, which is the whole point:
    a woman who has moved away or died cannot be visited, and until this
    existed her follow-up sat permanently overdue, counting against her
    ASHA's compliance and against the sub-centre's figures, with no way to
    clear it except to pretend the visit happened.

    What closing does not do is remove anything. Her visits, risk flags
    and the reports built from them are the record of care actually given;
    a district's historical figures must not move because somebody changed
    address. Reopening restores her to the caseload but does not revive
    the cancelled tasks -- if she is back, the next visit creates the next
    follow-up.
    """
    patient = _writable_patient(db, user, patient_id)

    if patient.status == payload.status:
        raise HTTPException(status_code=400, detail=f"Patient is already {payload.status}")

    previous = patient.status
    now = datetime.now(timezone.utc)
    patient.status = payload.status

    cancelled = 0
    if payload.status == "active":
        patient.closed_reason = None
        patient.closed_at = None
        patient.closed_by = None
    else:
        patient.closed_reason = payload.reason
        patient.closed_at = now
        patient.closed_by = user.worker_id
        cancelled = (
            db.query(Action)
            .filter(
                Action.action_id.in_(
                    db.query(Action.action_id)
                    .join(Visit, Action.visit_id == Visit.visit_id)
                    .filter(
                        Visit.patient_id == patient_id,
                        Action.type == "followup",
                        Action.status == "pending",
                    )
                )
            )
            .update({Action.status: "cancelled"}, synchronize_session=False)
        )

    db.commit()

    audit_record(
        db,
        user_id=user.worker_id,
        action_type="patient.status",
        record_id=patient_id,
        record_type="patient",
        details={
            "from": previous,
            "to": payload.status,
            "reason": payload.reason,
            "followups_cancelled": cancelled,
            "by_role": user.role,
        },
    )
    return PatientStatusResult(
        patient_id=patient_id,
        status=patient.status,
        closed_at=patient.closed_at,
        followups_cancelled=cancelled,
    )
