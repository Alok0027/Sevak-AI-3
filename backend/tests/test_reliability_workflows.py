import asyncio
import json
from uuid import uuid4
from datetime import datetime, timedelta, timezone
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.db.models.worker import Worker
from app.db.models.patient import Patient
from app.db.models.visit import Visit
from app.db.models.action import Action
from app.db.models.notification import Notification
from app.db.models.risk_flag import RiskFlag
from app.services import notifications
from fastapi import HTTPException
from app.schemas.visit import ExtractedFields
from app.services.visit_pipeline import run_voice_visit

def fixture_data():
    with SessionLocal() as db:
        centre = str(uuid4())
        users = []
        for role in ('asha', 'anm'):
            w = Worker(worker_id=str(uuid4()), name='Test', phone=str(uuid4()),
                       pin_hash='unused', role=role, sub_centre_id=centre, status='active')
            db.add(w)
            users.append(w.worker_id)
        p = Patient(patient_id=str(uuid4()), worker_id=users[0], name='Test patient', phone='9999990000')
        db.add(p)
        db.commit()
        return users, p.patient_id

def headers(worker, role='asha'):
    return {'Authorization': 'Bearer ' + create_access_token(worker, role)}

def visit_body(worker, patient):
    return {'worker_id': worker, 'patient_id': patient, 'client_request_id': str(uuid4()),
            'confirmed_transcript': 'Reviewed test observation',
            'confirmed_extracted': {'bp_systolic': 145, 'bp_diastolic': 95}}

def test_online_then_offline_retry_creates_exactly_one_visit_and_preserves_edits():
    users, patient = fixture_data()
    body = visit_body(users[0], patient)
    with TestClient(app) as client:
        first = client.post('/api/v1/visits/voice', headers=headers(users[0]), json=body)
        assert first.status_code == 200, first.text
        repeat = client.post('/api/v1/visits/voice', headers=headers(users[0]), json=body)
        assert repeat.json() == first.json()
        synced = client.post('/api/v1/sync/batch', headers=headers(users[0]), json={
            'worker_id': users[0], 'records': [{**body, 'record_type': 'visit'}]})
        assert synced.json()['synced'] == 1
        changed = client.post('/api/v1/visits/voice', headers=headers(users[0]), json={**body, 'confirmed_transcript': 'changed'})
        assert changed.status_code == 409
    with SessionLocal() as db:
        assert db.query(Visit).filter(Visit.patient_id == patient).count() == 1
        assert db.query(Visit).filter(Visit.patient_id == patient).one().transcript == body['confirmed_transcript']

def test_concurrent_visit_claim_has_only_one_winner():
    users, patient = fixture_data()
    request_id = str(uuid4())
    async def submit():
        with SessionLocal() as db:
            try:
                return await run_voice_visit(db, get_settings(), users[0], patient,
                    confirmed_transcript='Reviewed concurrent test',
                    confirmed_extracted=ExtractedFields(bp_systolic=120), client_request_id=request_id)
            except HTTPException as exc:
                assert exc.status_code == 409
                return None
    async def both():
        return await asyncio.gather(submit(), submit())
    results = asyncio.run(both())
    assert any(result is not None for result in results)
    with SessionLocal() as db:
        assert db.query(Visit).filter(Visit.patient_id == patient).count() == 1

def test_high_risk_visit_fires_immediate_alert_inline(monkeypatch):
    """FR-03.4: a HIGH classification has to page the ANM within 60 seconds --
    not "eventually, once a scheduler ticks." run_voice_visit is the one
    request-path entry point every voice visit goes through, so proving the
    immediate_alert Action exists right after it returns (no cron, no extra
    call) is what actually pins the 60-second requirement, as opposed to the
    unit tests in test_escalation_alerts.py which only prove
    build_immediate_alert works in isolation."""
    users, patient = fixture_data()
    sent = []

    class RecordingSms:
        async def send_message(self, phone, content):
            sent.append(content)
            return {'sid': 'test-immediate'}

    monkeypatch.setattr('app.services.visit_pipeline.get_sms_client', lambda settings: RecordingSms())
    with SessionLocal() as db:
        result = asyncio.run(run_voice_visit(
            db, get_settings().model_copy(update={'sms_provider': 'real'}), users[0], patient,
            confirmed_transcript='BP reading taken', client_request_id=str(uuid4()),
            confirmed_extracted=ExtractedFields(bp_systolic=180, bp_diastolic=120)))
        assert result.risk_level == 'HIGH'
        alerts = db.query(Action).filter(Action.visit_id == result.visit_id, Action.type == 'immediate_alert').all()
        assert len(alerts) == 1, "run_voice_visit must create exactly one immediate_alert for a fresh HIGH visit"
        assert alerts[0].status == 'sent'
        assert sent, "the immediate alert must be delivered inline, not left for a background worker"


def test_meta_preview_and_delivery_use_same_template_parameters(monkeypatch):
    users, patient = fixture_data()
    settings = get_settings().model_copy(update={'whatsapp_provider':'meta', 'whatsapp_template_name':'followup_reminder', 'whatsapp_template_language':'hi'})
    seen = []
    class FakeMeta:
        async def send_template(self, phone, template, params, language):
            seen.append((phone, template, params, language))
            return {'messages':[{'id':'test-wa-id'}]}
    monkeypatch.setattr(notifications, 'get_whatsapp_client', lambda settings: FakeMeta())
    with SessionLocal() as db:
        v = Visit(patient_id=patient, worker_id=users[0], risk_level='HIGH'); db.add(v); db.flush()
        a = Action(visit_id=v.visit_id, type='whatsapp', content='Different draft', status='queued'); db.add(a); db.flush()
        payload, _ = notifications.preview(a, v, db.get(Patient, patient), 'whatsapp', settings)
        assert 'उच्च जोखिम' in payload['text']
        assert payload['text'] != a.content
        db.add(Notification(action_id=a.action_id, payload_json=json.dumps(payload), approved_by=users[0])); db.commit()
        asyncio.run(notifications.deliver_due(db, settings))
        assert seen[-1][2] == payload['params']
        assert db.get(Notification, a.action_id).provider_id == 'test-wa-id'

def test_scheduler_creates_one_alert_and_resolution_prevents_new_escalation(monkeypatch):
    from scripts.process_notifications import run_once
    users, patient = fixture_data()
    settings = get_settings().model_copy(update={'sms_provider':'real'})
    class FakeSms:
        async def send_message(self, phone, content): return {'sid':'test-alert'}
    monkeypatch.setattr(notifications, 'get_sms_client', lambda settings: FakeSms())
    with SessionLocal() as db:
        v = Visit(patient_id=patient, worker_id=users[0], risk_level='HIGH'); db.add(v); db.flush()
        db.add(RiskFlag(visit_id=v.visit_id, risk_level='HIGH', created_at=datetime.now(timezone.utc)-timedelta(hours=49)))
        db.commit()
        asyncio.run(run_once(db, settings)); asyncio.run(run_once(db, settings))
        actions = db.query(Action).filter(Action.visit_id == v.visit_id, Action.type == 'escalation_alert').all()
        assert len(actions) == 1
        assert db.get(Notification, actions[0].action_id).attempts == 1

def test_retry_budget_and_abandoned_dispatch_are_not_infinite(monkeypatch):
    users, patient = fixture_data()
    calls = []
    class OfflineSms:
        async def send_message(self, phone, content):
            calls.append(1)
            raise httpx.ConnectError('offline')
    monkeypatch.setattr(notifications, 'get_sms_client', lambda settings: OfflineSms())
    with SessionLocal() as db:
        v = Visit(patient_id=patient, worker_id=users[0]); db.add(v); db.flush()
        a = Action(visit_id=v.visit_id, type='whatsapp', content='test', status='queued'); db.add(a); db.flush()
        item = Notification(action_id=a.action_id, approved_by=users[0], payload_json=json.dumps(
            {'channel':'sms', 'provider':'mock', 'phone':'9999990000', 'text':'test'}))
        db.add(item); db.commit()
        for _ in range(6):
            item.next_attempt_at = datetime.now(timezone.utc)-timedelta(seconds=1)
            db.commit()
            asyncio.run(notifications.deliver_due(db, get_settings()))
            db.refresh(item)
        assert item.status == 'failed'
        assert item.attempts == 5
        item.status = 'sending'
        item.next_attempt_at = datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
        before = len(calls)
        asyncio.run(notifications.deliver_due(db, get_settings()))
        db.refresh(item)
        assert item.status == 'needs_review'
        assert len(calls) == before

def test_approval_consent_hash_permissions_and_resolution():
    users, patient = fixture_data()
    with TestClient(app) as client:
        created = client.post('/api/v1/visits/voice', headers=headers(users[0]), json=visit_body(users[0], patient)).json()
        visit_id = created['visit_id']
        inbox = client.get('/api/v1/notifications', headers=headers(users[0])).json()['notifications']
        action = inbox[0]['action_id']
        assert inbox[0]['status'] == 'draft'
        preview = client.get(f'/api/v1/notifications/{action}/preview?channel=sms', headers=headers(users[0])).json()
        approval = {'channel': 'sms', 'preview_hash': preview['preview_hash'], 'consent_confirmed': True}
        url = f'/api/v1/notifications/{action}/approve'
        assert client.post(url, headers=headers(users[0]), json={**approval, 'consent_confirmed': False}).status_code == 409
        assert client.post(url, headers=headers(users[0]), json={**approval, 'preview_hash': 'stale'}).status_code == 409
        assert client.post(url, headers=headers(users[1], 'anm'), json=approval).status_code == 403
        assert client.post(url, headers=headers(users[0]), json=approval).json()['status'] == 'queued'
        assert client.post(url, headers=headers(users[0]), json=approval).json()['status'] == 'queued'
        with SessionLocal() as db:
            task = db.query(Action).filter(Action.visit_id == visit_id, Action.type == 'followup').one().action_id
        assert client.post(f'/api/v1/tasks/{task}/complete', headers=headers(users[0])).status_code == 200
        with SessionLocal() as db:
            assert db.query(RiskFlag).filter(RiskFlag.visit_id == visit_id).one().actioned_at is None
        url = f'/api/v1/visits/{visit_id}/resolve-risk'
        note = {'note': 'Reviewed by supervisor; follow-up findings documented.'}
        assert client.post(url, headers=headers(users[0]), json=note).status_code == 403
        assert client.post(url, headers=headers(users[1], 'anm'), json={'note': '   '}).status_code == 422
        assert client.post(url, headers=headers(users[1], 'anm'), json=note).status_code == 200
    with SessionLocal() as db:
        flag = db.query(RiskFlag).filter(RiskFlag.visit_id == visit_id).one()
        assert flag.actioned_at is not None
        assert flag.risk_level == 'HIGH'
        assert db.query(Notification).filter(Notification.action_id == action).count() == 1

@pytest.mark.parametrize('failure,expected', [(None, 'accepted'), (httpx.ConnectError('offline'), 'retry'), (httpx.ReadTimeout('unknown'), 'needs_review')])
def test_dispatch_acknowledgement_retry_and_unknown_outcome(monkeypatch, failure, expected):
    users, patient = fixture_data()
    calls = []
    class FakeSms:
        async def send_message(self, phone, message):
            calls.append((phone, message))
            if failure: raise failure
            return {'sid': 'test-provider-id', 'status': 'queued'}
    monkeypatch.setattr(notifications, 'get_sms_client', lambda settings: FakeSms())
    with SessionLocal() as db:
        v = Visit(patient_id=patient, worker_id=users[0]); db.add(v); db.flush()
        a = Action(visit_id=v.visit_id, type='whatsapp', content='Approved exact text', status='queued'); db.add(a); db.flush()
        db.add(Notification(action_id=a.action_id, payload_json=json.dumps({'channel':'sms', 'provider':'mock', 'phone':'9999990000', 'text':a.content}), approved_by=users[0]))
        db.commit()
        asyncio.run(notifications.deliver_due(db, get_settings()))
        item = db.get(Notification, a.action_id)
        assert item.status == expected
        assert item.attempts == 1
        assert calls[-1][1] == 'Approved exact text'
        before = len(calls)
        asyncio.run(notifications.deliver_due(db, get_settings()))
        assert len(calls) == before  # Accepted/uncertain/backoff entries are not resent.
