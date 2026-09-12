"""POST /api/v1/visits/transcribe (FR-01.4: transcribe-only, for review
before processing), POST /api/v1/visits/voice (the core end-to-end pipeline
endpoint), and POST /api/v1/visits/{visit_id}/risk-override (FR-03.3)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import DbSession, get_supervisor_scope, require_roles
from app.core.config import get_settings
from app.db.models.risk_flag import RiskFlag
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.agents import agent1_voice_comprehension as agent1
from app.schemas.visit import (
    ExtractRequest,
    ExtractResponse,
    RiskOverrideRequest,
    RiskOverrideResponse,
    TranscribeRequest,
    TranscribeResponse,
    VoiceVisitRequest,
    VoiceVisitResponse,
)
from app.services.audit import record as audit_record
from app.services.bhashini_client import get_bhashini_client
from app.services.llm_client import get_llm_client
from app.services.visit_pipeline import run_voice_visit

router = APIRouter(prefix="/api/v1/visits", tags=["visits"])


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_only(
    payload: TranscribeRequest,
    _user=Depends(require_roles("asha")),
) -> TranscribeResponse:
    """FR-01.4: transcribe a recording without running the rest of the
    pipeline, so the ASHA can see and correct what was heard before it
    feeds risk scoring, referral drafting, etc. Writes nothing to the DB --
    confirm via POST /visits/voice with confirmed_transcript set."""
    settings = get_settings()
    stt_client = get_bhashini_client(settings)
    transcript = await stt_client.transcribe(payload.audio_base64, payload.language_code)
    return TranscribeResponse(transcript=transcript)


@router.post("/extract", response_model=ExtractResponse)
async def extract_only(
    payload: ExtractRequest,
    _user=Depends(require_roles("asha")),
) -> ExtractResponse:
    """Pull the clinical fields out of a confirmed transcript without
    scoring or storing anything, so the ASHA can correct a misheard BP or
    temperature before it drives the risk classification -- the same
    review-before-trust step /transcribe gives the text, one level down.
    Uses the pipeline's own Agent 1 entry point, so what she reviews here
    is exactly what would otherwise have been used. Writes nothing to the
    DB -- confirm via POST /visits/voice with confirmed_extracted set."""
    settings = get_settings()
    extracted = await agent1.extract_with_llm(payload.transcript, get_llm_client(settings))
    return ExtractResponse(extracted=extracted)


@router.post("/voice", response_model=VoiceVisitResponse)
async def record_voice_visit(
    payload: VoiceVisitRequest,
    db: DbSession,
    _user=Depends(require_roles("asha")),
) -> VoiceVisitResponse:
    settings = get_settings()
    try:
        return await run_voice_visit(
            db=db,
            settings=settings,
            worker_id=payload.worker_id,
            patient_id=payload.patient_id,
            audio_base64=payload.audio_base64,
            language_code=payload.language_code,
            confirmed_transcript=payload.confirmed_transcript,
            confirmed_extracted=payload.confirmed_extracted,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{visit_id}/risk-override", response_model=RiskOverrideResponse)
def override_risk(
    visit_id: str,
    payload: RiskOverrideRequest,
    db: DbSession,
    user=Depends(require_roles("asha", "anm", "bmo")),
) -> RiskOverrideResponse:
    """FR-03.3: let the ASHA who recorded the visit, her ANM supervisor (own
    sub-centre only), or a BMO (district-wide) correct the AI's risk call
    with a mandatory reason. The correction becomes the risk level
    everywhere it's read from (dashboard, escalation queue, HMIS report) --
    it isn't a separate shadow field the rest of the app has to remember to
    check. What *is* kept alongside it is the full trail: the original AI
    call, who changed it, and why -- both on the risk_flags row (current
    state, for quick display) and as an append-only audit_log entry (full
    history across however many times it changes)."""
    visit = db.query(Visit).filter(Visit.visit_id == visit_id).first()
    if visit is None:
        raise HTTPException(status_code=404, detail="Visit not found")

    if user.role == "asha" and visit.worker_id != user.worker_id:
        raise HTTPException(status_code=403, detail="Not your visit")
    if user.role == "anm":
        scope = get_supervisor_scope(user, db)
        worker = db.query(Worker).filter(Worker.worker_id == visit.worker_id).first()
        if worker is None or worker.sub_centre_id != scope:
            raise HTTPException(status_code=403, detail="Visit is outside your sub-centre")
    # BMO: district-wide, no scope restriction (get_supervisor_scope returns
    # None for bmo everywhere else in the app -- same rule here).

    if payload.new_risk_level == visit.risk_level:
        raise HTTPException(
            status_code=400,
            detail=f"Visit is already {payload.new_risk_level} -- nothing to override",
        )

    risk_flag = db.query(RiskFlag).filter(RiskFlag.visit_id == visit_id).first()
    if risk_flag is None:
        raise HTTPException(status_code=500, detail="Visit has no risk record to override")

    overriding_worker = db.query(Worker).filter(Worker.worker_id == user.worker_id).first()

    previous_level = visit.risk_level
    now = datetime.now(timezone.utc)

    visit.risk_level = payload.new_risk_level
    risk_flag.risk_level = payload.new_risk_level
    risk_flag.overridden_by = user.worker_id
    risk_flag.override_reason = payload.reason
    db.commit()

    audit_record(
        db,
        user_id=user.worker_id,
        action_type="risk.override",
        record_id=visit_id,
        record_type="visit",
        details={
            "previous_risk_level": previous_level,
            "new_risk_level": payload.new_risk_level,
            "reason": payload.reason,
            "overridden_by_name": overriding_worker.name if overriding_worker else None,
            "overridden_by_role": user.role,
        },
    )

    return RiskOverrideResponse(
        visit_id=visit_id,
        patient_id=visit.patient_id,
        previous_risk_level=previous_level,
        new_risk_level=payload.new_risk_level,
        reason=payload.reason,
        overridden_by=user.worker_id,
        overridden_by_name=overriding_worker.name if overriding_worker else "Unknown",
        overridden_by_role=user.role,
        overridden_at=now,
    )
