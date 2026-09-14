"""Escalation has to reach a person.

Before this, `check_and_escalate` found HIGH flags unactioned past 48 hours
and set a database column. Nobody was told. The ANM learned about it only
if she happened to open the dashboard -- and the check itself only ran when
somebody did, so a district where no supervisor logged in for a week
escalated nothing at all.

These tests pin the two halves of the fix: that escalating produces an
addressed alert, and that the alert's failure modes stay visible instead of
becoming silence.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.agent5_escalation import (
    ESCALATION_THRESHOLD_HOURS,
    check_and_escalate,
    deliver_escalation_alerts,
)
from app.db.models.action import Action
from app.db.models.patient import Patient
from app.db.models.risk_flag import RiskFlag
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.db.session import SessionLocal
from app.services.sms_client import SmsClientBase


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _stale_high_flag(db, *, hours_old=ESCALATION_THRESHOLD_HOURS + 1, with_anm=True):
    """One ASHA, her ANM, a patient, and a HIGH flag nobody has touched."""
    # uuid, not a timestamp: two workers built in the same second got the
    # same phone number and tripped the unique constraint, which made these
    # tests pass alone and fail together.
    tag = uuid.uuid4().hex[:8]
    sub_centre = f"SC-TEST-{tag}"
    asha = Worker(name="Test ASHA", phone=f"9{uuid.uuid4().int % 10**9:09d}",
                  pin_hash="x", role="asha", sub_centre_id=sub_centre)
    db.add(asha)
    if with_anm:
        db.add(Worker(name="Test ANM", phone=f"9{uuid.uuid4().int % 10**9:09d}",
                      pin_hash="x", role="anm", sub_centre_id=sub_centre))
    db.flush()
    patient = Patient(worker_id=asha.worker_id, name="Kamla Devi", age=26, gender="female")
    db.add(patient); db.flush()
    created = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    visit = Visit(patient_id=patient.patient_id, worker_id=asha.worker_id,
                  risk_level="HIGH", created_at=created)
    db.add(visit); db.flush()
    flag = RiskFlag(visit_id=visit.visit_id, risk_level="HIGH", created_at=created)
    db.add(flag); db.commit()
    return flag


def _alerts_for(db, flag):
    return db.query(Action).filter(
        Action.visit_id == flag.visit_id, Action.type == "escalation_alert"
    ).all()


def test_escalating_produces_an_alert_addressed_to_the_anm(db):
    flag = _stale_high_flag(db)
    # `in`, not `==`: check_and_escalate sweeps every stale HIGH flag in the
    # district, and the seeded demo caseload puts others there. What this
    # test is about is that *this* flag escalated, not that it was alone.
    assert flag.flag_id in check_and_escalate(db)

    alerts = _alerts_for(db, flag)
    assert len(alerts) == 1, "the flag escalated without telling anyone"
    assert "Kamla Devi" in alerts[0].content
    assert "ANM" in alerts[0].content
    assert alerts[0].status == "pending"


def test_a_fresh_high_flag_is_not_escalated(db):
    flag = _stale_high_flag(db, hours_old=1)
    assert flag.flag_id not in check_and_escalate(db)
    assert _alerts_for(db, flag) == []


def test_escalation_is_not_repeated_on_the_next_run(db):
    """escalated_at is the guard. Without it, every visit recorded in the
    district would re-alert on every open flag."""
    flag = _stale_high_flag(db)
    check_and_escalate(db)
    before = len(_alerts_for(db, flag))
    check_and_escalate(db)
    assert len(_alerts_for(db, flag)) == before


def test_the_alert_is_actually_sent_when_a_channel_exists(db):
    # SmsClientBase, not MockSmsClient: delivery deliberately treats a mock
    # client as "no channel configured", so subclassing the mock made this
    # test assert that a real send happens over a client the code is
    # designed to ignore.
    class _Recording(SmsClientBase):
        def __init__(self):
            self.sent = []

        async def send_message(self, to, body):
            self.sent.append((to, body))
            return {"status": "sent"}

    flag = _stale_high_flag(db)
    check_and_escalate(db)
    sms = _Recording()
    # Not an exact count: delivery drains every pending alert in the
    # database, including ones other tests in this file left behind. The
    # assertion that means something is what happened to *this* flag.
    assert asyncio.run(deliver_escalation_alerts(db, sms_client=sms)) >= 1
    assert _alerts_for(db, flag)[0].status == "sent"
    assert any("Kamla Devi" in body for _, body in sms.sent), (
        f"this patient's alert never went out; sent {len(sms.sent)} others"
    )


def test_a_failed_send_is_recorded_not_swallowed(db):
    """A supervisor's phone being unreachable must be visible as a failed
    row, not as silence -- silence is indistinguishable from no alert."""
    class _Broken(SmsClientBase):
        async def send_message(self, to, body):
            raise RuntimeError("carrier rejected")

    flag = _stale_high_flag(db)
    check_and_escalate(db)
    assert asyncio.run(deliver_escalation_alerts(db, sms_client=_Broken())) == 0
    assert _alerts_for(db, flag)[0].status == "failed"
    # And the row is still there to be seen -- a failure that deletes its
    # own evidence is indistinguishable from never having tried.
    assert _alerts_for(db, flag)[0].content


def test_no_channel_leaves_the_alert_pending_rather_than_marking_it_sent(db):
    """So that turning SMS on later delivers the backlog instead of
    discovering it was quietly discarded."""
    flag = _stale_high_flag(db)
    check_and_escalate(db)
    assert asyncio.run(deliver_escalation_alerts(db)) == 0
    assert _alerts_for(db, flag)[0].status == "pending"


def test_a_sub_centre_with_no_anm_falls_back_to_the_bmo(db):
    """An alert with no recipient is the same as no alert."""
    flag = _stale_high_flag(db, with_anm=False)
    check_and_escalate(db)
    alerts = _alerts_for(db, flag)
    assert alerts, "no ANM meant no alert at all"
    assert "BMO" in alerts[0].content
