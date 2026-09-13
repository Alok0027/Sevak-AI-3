"""Orchestrates one full home-visit request: runs the Agent 1-4 graph, then
persists Visit / RiskFlag / Action rows and refreshes the running monthly
HMIS report -- everything POST /api/v1/visits/voice needs (NFR-P1: <30s
end-to-end, table 17 data flow)."""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agents import agent4_reporting as agent4
from app.agents.graph import build_pipeline_graph
from app.core.config import Settings
from app.db.models.action import Action
from app.db.models.patient import Patient
from app.db.models.risk_flag import RiskFlag
from app.db.models.visit import Visit
from app.agents.agent5_escalation import check_and_escalate, deliver_escalation_alerts
from app.schemas.visit import ExtractedFields, RiskDriver, VoiceVisitResponse
from app.services.audit import record as audit_record
from app.services.bhashini_client import get_bhashini_client
from app.services.llm_client import get_llm_client
from app.services.sms_client import get_sms_client
from app.services.whatsapp_client import get_whatsapp_client

logger = logging.getLogger(__name__)


async def run_voice_visit(
    db: Session,
    settings: Settings,
    worker_id: str,
    patient_id: str,
    audio_base64: str | None = None,
    language_code: str = "hi",
    confirmed_transcript: str | None = None,
    confirmed_extracted: ExtractedFields | None = None,
) -> VoiceVisitResponse:
    """FR-01.4: pass `confirmed_transcript` to skip re-transcription and run
    the rest of the pipeline on exactly the text the ASHA already reviewed
    (see POST /visits/transcribe). Falls back to transcribing `audio_base64`
    when no confirmed transcript is given, same as before."""
    if not audio_base64 and not confirmed_transcript:
        raise ValueError("audio_base64 or confirmed_transcript is required")

    patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
    if patient is None:
        raise ValueError(f"Unknown patient_id: {patient_id}")

    bhashini_client = get_bhashini_client(settings)
    llm_client = get_llm_client(settings)
    whatsapp_client = get_whatsapp_client(settings)
    sms_client = get_sms_client(settings)
    graph = build_pipeline_graph(bhashini_client, llm_client, whatsapp_client, sms_client)

    initial_state = {
        "worker_id": worker_id,
        "patient_id": patient_id,
        "patient_name": patient.name,
        "patient_phone": patient.phone,
        "language_code": language_code,
    }
    if confirmed_transcript:
        initial_state["confirmed_transcript"] = confirmed_transcript
    if confirmed_extracted:
        initial_state["confirmed_extracted"] = confirmed_extracted
    if audio_base64:
        initial_state["audio_base64"] = audio_base64

    result = await graph.ainvoke(initial_state)

    extracted: ExtractedFields = result["extracted"]
    risk_level: str = result["risk_level"]
    risk_score: float = result["risk_score"]
    risk_drivers: list[RiskDriver] = result["risk_drivers"]
    actions: list[dict] = result["actions"]

    visit = Visit(
        patient_id=patient_id,
        worker_id=worker_id,
        transcript=result["transcript"],
        structured_json=json.dumps(extracted.model_dump()),
        risk_score=risk_score,
        risk_level=risk_level,
    )
    db.add(visit)
    db.flush()  # get visit.visit_id before we reference it

    risk_flag = RiskFlag(
        visit_id=visit.visit_id,
        risk_level=risk_level,
        drivers_json=json.dumps([d.model_dump() for d in risk_drivers]),
    )
    db.add(risk_flag)

    for action in actions:
        db.add(
            Action(
                visit_id=visit.visit_id,
                type=action["type"],
                content=action["content"],
                status=action.get("status", "draft"),
                due_at=datetime.fromisoformat(action["due_at"]) if action.get("due_at") else None,
                sent_at=datetime.now(timezone.utc) if action.get("status") in ("sent", "mock_sent") else None,
            )
        )

    db.commit()

    # FR-06: run the 48-hour escalation check here rather than only when a
    # supervisor opens the dashboard. A patient who has been HIGH and
    # untouched for two days should not depend on someone happening to look,
    # and this is the one code path guaranteed to run while anyone in the
    # district is working. The check is a single indexed query; the send is
    # wrapped so an unreachable supervisor cannot fail this ASHA's visit.
    try:
        escalated = check_and_escalate(db)
        if escalated:
            await deliver_escalation_alerts(db, whatsapp_client, sms_client)
    except Exception:  # noqa: BLE001 -- escalation must never lose a visit
        logger.exception("escalation check failed after visit %s", visit.visit_id)
    db.refresh(visit)

    audit_record(db, user_id=worker_id, action_type="visit.create", record_id=visit.visit_id, record_type="visit")

    now = datetime.now(timezone.utc)
    agent4.regenerate_monthly_report(db, worker_id=worker_id, month=now.month, year=now.year)

    return VoiceVisitResponse(
        visit_id=visit.visit_id,
        transcript=result["transcript"],
        extracted=extracted,
        risk_level=risk_level,
        risk_score=risk_score,
        risk_drivers=risk_drivers,
        actions_generated=actions,
    )
