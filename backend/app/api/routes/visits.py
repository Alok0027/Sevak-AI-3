"""POST /api/v1/visits/transcribe (FR-01.4: transcribe-only, for review
before processing), POST /api/v1/visits/voice (the core end-to-end pipeline
endpoint), and POST /api/v1/visits/{visit_id}/risk-override (FR-03.3)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from app.api.deps import require_worker_access
from app.db.models.risk_resolution import RiskResolution
from app.db.models.notification import Notification
from app.db.models.action import Action
from app.db.models.audit_log import AuditLog
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, get_supervisor_scope, require_roles
from app.core.config import get_settings
from app.db.models.patient import Patient
from app.db.models.risk_flag import RiskFlag
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.agents import agent1_voice_comprehension as agent1
from app.agents.agent3_action_generation import DEFAULT_PHC, FOLLOWUP_DAYS
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
from app.services import cover
from app.services.audit import record as audit_record
from app.services.bhashini_client import get_bhashini_client
from app.services.llm_client import get_llm_client
from app.services.visit_pipeline import run_voice_visit

router = APIRouter(prefix="/api/v1/visits", tags=["visits"])

class ResolveRiskRequest(BaseModel):
    note: str = Field(min_length=10, max_length=2000)

    @field_validator("note")
    @classmethod
    def meaningful_note(cls, value):
        if len(value.strip()) < 10:
            raise ValueError("A resolution note of at least 10 characters is required")
        return value.strip()


def _cancel_pending_escalations(db, visit_id: str) -> None:
    """Withdraw any not-yet-delivered escalation alert for this visit.

    Shared by resolve-risk and a downgrading risk-override: both are ways
    a visit stops being an open HIGH case, and either way an ANM should
    not be paged about a risk level that is no longer current. An alert
    already sent is left alone -- it already happened and the audit trail
    should say so, not pretend it didn't.
    """
    for action in db.query(Action).filter(Action.visit_id == visit_id, Action.type == "escalation_alert").all():
        notification = db.get(Notification, action.action_id)
        if notification is not None and notification.status in ("queued", "retry"):
            notification.status = "cancelled"
            action.status = "cancelled"
        elif notification is None and action.status in ("pending", "failed"):
            action.status = "cancelled"


@router.post("/{visit_id}/resolve-risk")
def resolve_risk(visit_id: str, payload: ResolveRiskRequest, db: DbSession,
                 user=Depends(require_roles("anm", "bmo"))):
    visit = db.get(Visit, visit_id)
    if visit is None:
        raise HTTPException(404, "Visit not found")
    require_worker_access(user, db, visit.worker_id)
    existing = db.get(RiskResolution, visit_id)
    if existing:
        return {"status": "resolved", "resolved_by": existing.resolved_by}
    flag = db.query(RiskFlag).filter(RiskFlag.visit_id == visit_id).first()
    if flag is None:
        raise HTTPException(404, "Risk flag not found")
    now = datetime.now(timezone.utc)
    db.add(RiskResolution(visit_id=visit_id, resolved_by=user.worker_id, note=payload.note, resolved_at=now))
    flag.actioned_at = now
    # Keep the historical risk classification. Resolution is a separate human decision.
    _cancel_pending_escalations(db, visit_id)
    db.add(AuditLog(user_id=user.worker_id, action_type="risk.resolve", record_id=visit_id, record_type="visit"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.get(RiskResolution, visit_id) is None:
            raise
    return {"status": "resolved", "resolved_by": db.get(RiskResolution, visit_id).resolved_by}


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
    user=Depends(require_roles("asha")),
) -> VoiceVisitResponse:
    """Record a visit.

    Two guards that were not here before, and the second is why the first
    had to be written.

    The visit is filed against the signed-in worker, not against whatever
    worker_id the request carried. The pipeline never checked, so an ASHA
    could post a visit under a colleague's name -- inflating that
    colleague's numbers on the accountability dashboard, or hiding her own
    workload behind somebody else's.

    And the patient has to be one this worker can actually see: her own,
    or one belonging to a colleague she is covering for while that
    colleague is away. That check had to exist before cover could, because
    "anyone may record for anyone" is not an access rule, it is the
    absence of one.
    """
    settings = get_settings()
    patient = db.query(Patient).filter(Patient.patient_id == payload.patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if patient.worker_id not in cover.visible_worker_ids(db, user.worker_id):
        raise HTTPException(status_code=403, detail="Not your patient")

    try:
        return await run_voice_visit(
            db=db,
            settings=settings,
            # Hers, always. She walked to the house; the record says so,
            # and a covered visit is honestly attributed to whoever made
            # it rather than to the woman on leave.
            worker_id=user.worker_id,
            patient_id=payload.patient_id,
            audio_base64=payload.audio_base64,
            language_code=payload.language_code,
            confirmed_transcript=payload.confirmed_transcript,
            confirmed_extracted=payload.confirmed_extracted,
            client_request_id=payload.client_request_id,
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
    history across however many times it changes).

    The label is not the only thing a risk level drives, so the override
    also touches the work downstream of it:

    - The pending follow-up's due date moves to match the new risk tier
      (still anchored to the original visit time, not to whenever the
      override happened -- a visit from three days ago that gets upgraded
      to HIGH is already partway through its 48 hours, not freshly due in
      two more days).
    - Downgrading away from HIGH withdraws any escalation alert that
      hasn't gone out yet, same as resolving the risk does -- an ANM
      should not be paged about a level that's no longer current.
    - Upgrading into HIGH drafts a referral letter if the visit doesn't
      already have one, since FR-04.1 says every HIGH visit gets one and
      this is now a HIGH visit.

    Nothing here sends a message. A referral drafted this way is still a
    draft, same as one Agent 3 writes -- it goes through the same
    ASHA-approval flow (see app/api/routes/notifications.py) before
    anyone sees it.
    """
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

    if db.get(RiskResolution, visit_id) is not None:
        raise HTTPException(409, "This visit was resolved; record a new clinical assessment instead of rewriting it")
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

    # Follow-up deadline: recomputed for the new tier, anchored to the
    # visit itself so a late override doesn't hand out a fresh 48 hours.
    followup = (
        db.query(Action)
        .filter(Action.visit_id == visit_id, Action.type == "followup", Action.status == "pending")
        .first()
    )
    if followup is not None:
        due_days = FOLLOWUP_DAYS.get(payload.new_risk_level, 30)
        followup.due_at = visit.created_at + timedelta(days=due_days)

    if previous_level == "HIGH" and payload.new_risk_level != "HIGH":
        _cancel_pending_escalations(db, visit_id)
        referral = (
            db.query(Action)
            .filter(Action.visit_id == visit_id, Action.type == "referral", Action.status == "draft")
            .first()
        )
        if referral is not None:
            referral.status = "cancelled"

    if previous_level != "HIGH" and payload.new_risk_level == "HIGH":
        has_referral = (
            db.query(Action)
            .filter(Action.visit_id == visit_id, Action.type == "referral", Action.status != "cancelled")
            .first()
        )
        if has_referral is None:
            patient = db.get(Patient, visit.patient_id)
            referral_text = (
                f"REFERRAL LETTER\n\n"
                f"To: {DEFAULT_PHC}\n"
                f"Patient: {patient.name if patient else 'Unknown'}\n\n"
                f"Reason for referral (HIGH risk, set by {user.role} override): {payload.reason}\n\n"
                f"Please prioritise clinical review at earliest opportunity.\n"
                f"-- Generated by SevakAI"
            )
            db.add(Action(visit_id=visit_id, type="referral", content=referral_text, status="draft"))

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
