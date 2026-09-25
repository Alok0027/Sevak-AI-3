"""Orchestrates one full home-visit request: runs the Agent 1-4 graph, then
persists Visit / RiskFlag / Action rows and refreshes the running monthly
HMIS report -- everything POST /api/v1/visits/voice needs (NFR-P1: <30s
end-to-end, table 17 data flow)."""
import json
import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from app.db.models.visit_request import VisitRequest

from app.agents import agent4_reporting as agent4
from app.agents.graph import build_pipeline_graph
from app.core.config import Settings
from app.db.models.action import Action
from app.db.models.patient import Patient
from app.db.models.risk_flag import RiskFlag
from app.db.models.visit import Visit
from app.agents.agent5_escalation import build_immediate_alert, check_and_escalate, deliver_escalation_alerts
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
    client_request_id: str | None = None,
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

    receipt = None
    if client_request_id:
        request_key = hashlib.sha256(f"{worker_id}:{client_request_id}".encode()).hexdigest()
        canonical = json.dumps({
            "patient_id": patient_id, "language_code": language_code,
            "audio": None if confirmed_transcript else audio_base64,
            "transcript": confirmed_transcript,
            "fields": confirmed_extracted.model_dump() if confirmed_extracted is not None else None,
        }, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        receipt = VisitRequest(request_key=request_key, payload_hash=digest)
        db.add(receipt)
        try:
            db.commit()  # Unique insert claims this operation across processes.
        except IntegrityError:
            db.rollback()
            receipt = db.get(VisitRequest, request_key)
            if receipt is None or receipt.payload_hash != digest:
                raise HTTPException(409, "Request ID was already used for different visit data")
            if receipt.response_json is None:
                # Never blindly repeat a request whose external outcome is unknown.
                raise HTTPException(409, "Visit is processing or requires recovery; keep the same request ID")
            return VoiceVisitResponse.model_validate_json(receipt.response_json)

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
        "sub_centre_id": patient.sub_centre_id,
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

    response = VoiceVisitResponse(
        visit_id=visit.visit_id, transcript=result["transcript"], extracted=extracted,
        risk_level=risk_level, risk_score=risk_score, risk_drivers=risk_drivers,
        actions_generated=actions,
    )
    if receipt is not None:
        receipt.response_json = response.model_dump_json()
    db.commit()  # Visit, actions, risk flag and replay response become durable together.

    # FR-03.4: a HIGH classification pages the ANM within 60 seconds, no
    # follow-up required and no waiting for a background worker -- a
    # target that measured in seconds cannot be met by a cron that ticks
    # once a minute, so this sends inline, in the same request. Wrapped
    # the same way the 48-hour check below is: a supervisor's unreachable
    # phone must not fail the ASHA's visit.
    if risk_level == "HIGH":
        try:
            alert = build_immediate_alert(db, risk_flag)
            if alert is not None:
                db.add(alert)
                db.commit()
                # Scoped to this visit: the backlog is the outbox worker's
                # problem, not something to make an ASHA wait through.
                await deliver_escalation_alerts(db, sms_client, visit_id=visit.visit_id)
        except Exception:  # noqa: BLE001 -- see above
            logger.exception("immediate HIGH-risk alert failed after visit %s", visit.visit_id)

    # Patient message, sent rather than drafted, when the deployment asks
    # for it (settings.auto_send_patient_messages).
    #
    # Normally Agent 3's message waits as a draft: the ASHA opens it,
    # reads the exact text, confirms the patient agreed to be contacted on
    # that number, and only then does it go. That consent step is the
    # right default and it stays the default.
    #
    # Switched on, the pipeline runs end to end without a human in it --
    # a recorded visit produces a delivered message. Failures are recorded
    # on the action, never raised: a patient's phone being unreachable
    # must not fail the ASHA's visit, exactly as with the supervisor
    # alert above.
    if settings.auto_send_patient_messages and patient.phone:
        await _send_patient_message(db, settings, visit, patient, whatsapp_client, sms_client)

    # FR-06.1: run the 48-hour escalation check here rather than only when a
    # supervisor opens the dashboard. A patient who has been HIGH and
    # untouched for two days should not depend on someone happening to look,
    # and this is the one code path guaranteed to run while anyone in the
    # district is working. The check is a single indexed query; the send is
    # deferred to the independent outbox worker -- see agent5_escalation's
    # module docstring for why the two alerts don't share a clock.
    try:
        escalated = check_and_escalate(db)
        # Delivery belongs to the independent outbox worker, never this request.
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


async def _send_patient_message(db, settings, visit, patient, whatsapp_client, sms_client) -> None:
    """Deliver the message Agent 3 wrote for this patient, now.

    WhatsApp goes as the approved template, for the reason the config
    explains: a follow-up reminder is business-initiated, so Meta refuses
    free-form text outside a 24-hour window (131047). The LLM's fuller
    wording is still what is stored and shown in the app -- the template
    is only what WhatsApp permits to be delivered.

    SMS carries the full text, because nothing restricts its wording.
    """
    from app.services.notifications import preview
    from app.services.sms_client import MockSmsClient
    from app.services.whatsapp_client import MockWhatsAppClient

    action = (
        db.query(Action)
        .filter(Action.visit_id == visit.visit_id, Action.type == "whatsapp")
        .first()
    )
    if action is None:
        return

    for channel, client in (("whatsapp", whatsapp_client), ("sms", sms_client)):
        if client is None:
            continue
        mocked = isinstance(client, (MockWhatsAppClient, MockSmsClient))
        try:
            payload, _ = preview(action, visit, patient, channel, settings)
        except Exception:  # noqa: BLE001 -- no phone, unverified template
            continue
        try:
            if payload.get("template"):
                result = await client.send_template(
                    payload["phone"], payload["template"], payload["params"], payload["language"]
                )
            else:
                result = await client.send_message(payload["phone"], payload["text"])
            action.status = "mock_sent" if mocked else "sent"
            action.sent_at = datetime.now(timezone.utc)
            db.commit()
            audit_record(
                db, user_id=visit.worker_id, action_type="patient.message.sent",
                record_id=action.action_id, record_type="action",
                details={"channel": channel, "auto": True,
                         "provider_result": str(result.get("status", "accepted"))[:40]},
            )
            # One channel is enough. Two messages about one visit is noise
            # to her and spend to the deployment.
            return
        except Exception as exc:  # noqa: BLE001 -- see docstring
            logger.warning("auto-send over %s failed: %s", channel, exc)
            action.status = "failed"
            db.commit()
