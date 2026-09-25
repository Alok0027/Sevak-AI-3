"""Sending the patient her message without an approval tap.

Off by default: the approval step is where the ASHA confirms the patient
agreed to be contacted on that number, and a system that texts a pregnant
woman without anyone asking is not a thing to discover afterwards.

On, the pipeline runs end to end with no human in it -- which is what a
demonstration of the whole workflow needs, and what a deployment that
captures consent elsewhere would want.
"""
import asyncio
import base64

import pytest

from app.core.config import get_settings
from app.db.models.action import Action
from app.db.models.audit_log import AuditLog
from app.db.models.patient import Patient
from app.db.session import SessionLocal
from app.services.visit_pipeline import run_voice_visit
from scripts.seed_synthetic_data import seed_demo_fixtures

TRANSCRIPT = (
    "Meera Patil, 28 saal, 7 mahine ki pregnancy. Aaj BP 160 over 110 tha. "
    "Usne pichle 2 hafte se iron tablets nahi li."
)


class _Recording:
    """Stands in for a provider, and remembers what it was asked to send."""

    def __init__(self):
        self.messages = []
        self.templates = []

    async def send_message(self, to, body):
        self.messages.append((to, body))
        return {"status": "accepted"}

    async def send_template(self, to, name, params=None, language="hi"):
        self.templates.append((to, name, params))
        return {"status": "accepted"}


@pytest.fixture
def patient_with_phone():
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
        from app.db.models.worker import Worker

        worker = db.query(Worker).filter(Worker.phone == "9999999999").first()
        patient = Patient(worker_id=worker.worker_id, name="Auto Send Test",
                          age=28, gender="female", village="Wagholi",
                          phone="9876500011", pregnancy_stage="7 months")
        db.add(patient)
        db.commit()
        yield worker.worker_id, patient.patient_id
    finally:
        db.rollback()
        db.close()


async def _record(worker_id, patient_id, settings):
    db = SessionLocal()
    try:
        return await run_voice_visit(
            db=db, settings=settings, worker_id=worker_id, patient_id=patient_id,
            audio_base64=base64.b64encode(TRANSCRIPT.encode()).decode(),
            language_code="hi",
        ), db
    finally:
        pass


def test_off_by_default_the_message_waits_as_a_draft(patient_with_phone):
    worker_id, patient_id = patient_with_phone
    settings = get_settings().model_copy(update={"auto_send_patient_messages": False})

    result, db = asyncio.run(_record(worker_id, patient_id, settings))
    try:
        action = (
            db.query(Action)
            .filter(Action.visit_id == result.visit_id, Action.type == "whatsapp")
            .one()
        )
        assert action.status == "draft", (
            "nothing may reach a patient before her ASHA has confirmed consent"
        )
        assert action.sent_at is None
    finally:
        db.close()


def test_switched_on_the_visit_delivers_the_message_itself(patient_with_phone, monkeypatch):
    worker_id, patient_id = patient_with_phone
    whatsapp, sms = _Recording(), _Recording()

    import app.services.visit_pipeline as pipeline

    monkeypatch.setattr(pipeline, "get_whatsapp_client", lambda s: whatsapp)
    monkeypatch.setattr(pipeline, "get_sms_client", lambda s: sms)

    settings = get_settings().model_copy(update={
        "auto_send_patient_messages": True,
        "whatsapp_provider": "meta",
        "whatsapp_template_name": "followup_reminder",
        "whatsapp_template_language": "hi",
    })

    result, db = asyncio.run(_record(worker_id, patient_id, settings))
    try:
        assert whatsapp.templates, "nothing was sent to the patient"
        to, name, params = whatsapp.templates[0]
        assert to == "9876500011"
        assert name == "followup_reminder"
        # Her name, her risk in her language, and when to go.
        assert params[0] == "Auto Send Test"

        action = (
            db.query(Action)
            .filter(Action.visit_id == result.visit_id, Action.type == "whatsapp")
            .one()
        )
        assert action.status == "sent"
        assert action.sent_at is not None

        # And it is on the record that this went without a human approving.
        entry = (
            db.query(AuditLog)
            .filter(AuditLog.action_type == "patient.message.sent",
                    AuditLog.record_id == action.action_id)
            .one()
        )
        assert '"auto": true' in entry.details.lower()
    finally:
        db.close()


def test_one_message_per_visit_not_two(patient_with_phone, monkeypatch):
    """WhatsApp and SMS carry the same sentence. Sending both is noise to
    her and spend to the deployment."""
    worker_id, patient_id = patient_with_phone
    whatsapp, sms = _Recording(), _Recording()

    import app.services.visit_pipeline as pipeline

    monkeypatch.setattr(pipeline, "get_whatsapp_client", lambda s: whatsapp)
    monkeypatch.setattr(pipeline, "get_sms_client", lambda s: sms)

    settings = get_settings().model_copy(update={
        "auto_send_patient_messages": True, "whatsapp_provider": "meta",
    })
    _, db = asyncio.run(_record(worker_id, patient_id, settings))
    db.close()

    # Count only what went to *her*. A HIGH visit also pages the
    # supervisor by SMS, on the same client -- that is a different message
    # to a different person, and counting it here made this test fail for
    # a reason that had nothing to do with what it is checking.
    HER = "9876500011"
    to_patient = (
        [t for t in whatsapp.templates if t[0] == HER]
        + [m for m in whatsapp.messages if m[0] == HER]
        + [m for m in sms.messages if m[0] == HER]
    )
    assert len(to_patient) == 1, (
        f"expected exactly one message to the patient, sent {len(to_patient)}"
    )
