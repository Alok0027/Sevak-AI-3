"""GET /api/v1/patients/{worker_id} (FR-07.2: patient list with risk badges)
and GET /api/v1/patients/{patient_id}/history (full visit timeline)."""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func

from app.api.deps import DbSession, get_supervisor_scope, require_roles
from app.core.config import get_settings
from app.db.models.patient import Patient
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.schemas.patient import (
    PatientCreate,
    PatientListResponse,
    PatientSummary,
    PatientVoiceIntakeRequest,
    PatientVoiceIntakeResponse,
)
from app.schemas.worker import PatientHistoryEntry, PatientHistoryResponse
from app.services import patient_intake
from app.services.bhashini_client import get_bhashini_client

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
        db.query(Visit)
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
        )
        for v in rows
    ]
    return PatientHistoryResponse(
        patient_id=patient_id,
        patient_name=patient.name,
        worker_id=patient.worker_id,
        worker_name=worker.name if worker else "Unknown",
        village=patient.village,
        age=patient.age,
        pregnancy_stage=patient.pregnancy_stage,
        visits=visits,
    )
