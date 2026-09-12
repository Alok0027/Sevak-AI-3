"""GET /api/v1/patients/{worker_id} (FR-07.2: patient list with risk badges)
and GET /api/v1/patients/{patient_id}/history (full visit timeline)."""
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import aliased

from app.api.deps import DbSession, get_supervisor_scope, require_roles
from app.core.config import get_settings
from app.db.models.patient import Patient
from app.db.models.risk_flag import RiskFlag
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.schemas.patient import (
    PatientCreate,
    PatientDirectoryEntry,
    PatientDirectoryResponse,
    PatientListResponse,
    PatientSummary,
    PatientVoiceIntakeRequest,
    PatientVoiceIntakeResponse,
)
from app.schemas.worker import PatientHistoryEntry, PatientHistoryResponse
from app.services import patient_intake
from app.services.audit import record as audit_record
from app.services.bhashini_client import get_bhashini_client

# Aliased because a patient's assigned worker and the worker who overrode a
# visit's risk level (could be a different ASHA, or her ANM/BMO) are two
# different rows in the same table.
OverridingWorker = aliased(Worker)

router = APIRouter(prefix="/api/v1/patients", tags=["patients"])


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
    extracted = patient_intake.extract(transcript)
    return PatientVoiceIntakeResponse(transcript=transcript, extracted=extracted)


@router.post("", response_model=PatientSummary, status_code=201)
def create_patient(
    payload: PatientCreate,
    db: DbSession,
    user=Depends(require_roles("asha")),
) -> PatientSummary:
    """FR-07.2 prerequisite: register a new patient under the signed-in
    ASHA worker. She's the only one who registers her own patients from
    the field -- ANM/BMO only ever view/aggregate what she's recorded."""
    patient = Patient(
        worker_id=user.worker_id,
        name=payload.name.strip(),
        age=payload.age,
        gender=payload.gender,
        village=payload.village.strip() if payload.village else None,
        phone=payload.phone,
        pregnancy_stage=payload.pregnancy_stage,
        bp_systolic=payload.bp_systolic,
        bp_diastolic=payload.bp_diastolic,
        blood_sugar_fasting=payload.blood_sugar_fasting,
        blood_sugar_random=payload.blood_sugar_random,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return PatientSummary(
        id=patient.patient_id,
        name=patient.name,
        age=patient.age,
        village=patient.village,
        pregnancy_stage=patient.pregnancy_stage,
        risk_status=None,
        last_visit=None,
        total_visits=0,
    )


@router.get("", response_model=PatientDirectoryResponse)
def list_all_patients(
    db: DbSession,
    user=Depends(require_roles("anm", "bmo", "admin")),
    sub_centre_id: str | None = Query(default=None, description="BMO/Admin only: filter to one sub-centre"),
) -> PatientDirectoryResponse:
    """FR-08 drill-down: 'which patients are my ASHA workers actually
    treating right now' -- every patient across the ANM's own sub-centre,
    or (BMO/Admin) the whole district, in one place. The per-worker
    GET /patients/{worker_id} above can't answer that; it only ever shows
    one ASHA's patients at a time, so a supervisor would have to open every
    worker one by one to see who's being treated. The dashboard's Patients
    page filters this list client-side (gender, risk level, registration
    date, name search) -- this endpoint just returns the properly-scoped
    set for it to filter."""
    scope = get_supervisor_scope(user, db)
    effective_sub_centre = scope or sub_centre_id

    rows = (
        db.query(Patient, Worker)
        .join(Worker, Patient.worker_id == Worker.worker_id)
        .filter(Worker.role == "asha")
    )
    if effective_sub_centre:
        rows = rows.filter(Worker.sub_centre_id == effective_sub_centre)
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

    entries = [
        PatientDirectoryEntry(
            id=p.patient_id,
            name=p.name,
            age=p.age,
            gender=p.gender,
            village=p.village,
            pregnancy_stage=p.pregnancy_stage,
            risk_status=last_visit_by_patient[p.patient_id].risk_level if p.patient_id in last_visit_by_patient else None,
            last_visit=last_visit_by_patient[p.patient_id].created_at if p.patient_id in last_visit_by_patient else None,
            total_visits=visit_counts.get(p.patient_id, 0),
            registered_at=p.created_at,
            worker_id=w.worker_id,
            worker_name=w.name,
            sub_centre_id=w.sub_centre_id,
        )
        for p, w in rows
    ]
    audit_record(
        db,
        user_id=user.worker_id,
        action_type="patient.directory_view",
        record_type="patient",
        details={"sub_centre_id": effective_sub_centre, "result_count": len(entries)},
    )
    return PatientDirectoryResponse(patients=entries)


@router.get("/{worker_id}", response_model=PatientListResponse)
def list_patients(
    worker_id: str,
    db: DbSession,
    _user=Depends(require_roles("asha", "anm", "bmo", "admin")),
) -> PatientListResponse:
    patients = db.query(Patient).filter(Patient.worker_id == worker_id).all()
    visit_counts = dict(
        db.query(Visit.patient_id, func.count(Visit.visit_id))
        .filter(Visit.patient_id.in_([p.patient_id for p in patients]))
        .group_by(Visit.patient_id)
        .all()
    ) if patients else {}

    summaries = []
    for p in patients:
        last_visit = (
            db.query(Visit)
            .filter(Visit.patient_id == p.patient_id)
            .order_by(Visit.created_at.desc())
            .first()
        )
        summaries.append(
            PatientSummary(
                id=p.patient_id,
                name=p.name,
                age=p.age,
                village=p.village,
                pregnancy_stage=p.pregnancy_stage,
                risk_status=last_visit.risk_level if last_visit else None,
                last_visit=last_visit.created_at if last_visit else None,
                total_visits=visit_counts.get(p.patient_id, 0),
            )
        )
    return PatientListResponse(patients=summaries)


@router.get("/{patient_id}/history", response_model=PatientHistoryResponse)
def patient_history(
    patient_id: str,
    db: DbSession,
    user=Depends(require_roles("asha", "anm", "bmo", "admin")),
) -> PatientHistoryResponse:
    patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    worker = db.query(Worker).filter(Worker.worker_id == patient.worker_id).first()

    if user.role == "asha" and patient.worker_id != user.worker_id:
        raise HTTPException(status_code=403, detail="Not your patient")
    scope = get_supervisor_scope(user, db)
    if scope and (worker is None or worker.sub_centre_id != scope):
        raise HTTPException(status_code=403, detail="Patient is outside your sub-centre")

    rows = (
        db.query(Visit, RiskFlag, OverridingWorker)
        .outerjoin(RiskFlag, RiskFlag.visit_id == Visit.visit_id)
        .outerjoin(OverridingWorker, OverridingWorker.worker_id == RiskFlag.overridden_by)
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
        )
        for v, rf, ow in rows
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
