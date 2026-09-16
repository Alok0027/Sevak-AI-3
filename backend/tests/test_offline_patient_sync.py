"""Registering a patient offline, and the ordering problem inside it.

Before this, sync/batch processed only visits. A patient registered with no
signal was written to sync_queue and never applied -- so a morning's work in
a village with no coverage came back as a queue that had "synced" and a
patient who did not exist.

The ordering matters as much as the handling. A visit recorded offline for a
patient registered offline references a patient_id the server has never
seen; applied in arrival order it fails the visit, then succeeds the
patient, and retries forever.
"""
import random
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.models.patient import Patient
from app.db.session import SessionLocal
from app.main import app

DEMO_ASHA = {"phone": "9999999999", "pin": "1234"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth(client):
    r = client.post("/api/v1/auth/login", json=DEMO_ASHA)
    assert r.status_code == 200
    body = r.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["worker_id"]


def _fresh_rch() -> str:
    """A 12-digit number nothing else in the suite has claimed.

    rch_number is unique across the whole table and the tests share one
    database, so a hardcoded number passes in isolation and fails the
    moment another module registers it first -- which is exactly the bug
    this column is meant to catch in production.
    """
    return f"9{random.randrange(10**10, 10**11):011d}"


def _patient_record(**over):
    rec = {
        "record_type": "patient",
        "patient_id": str(uuid.uuid4()),
        "name": "Lakshmi Bai",
        "age": 27,
        "gender": "female",
        "village": "Wagholi",
    }
    rec.update(over)
    return rec


def test_a_patient_registered_offline_arrives(client, auth):
    headers, worker_id = auth
    rec = _patient_record()
    r = client.post("/api/v1/sync/batch",
                    json={"worker_id": worker_id, "records": [rec]}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["synced"] == 1

    db = SessionLocal()
    try:
        saved = db.query(Patient).filter(Patient.patient_id == rec["patient_id"]).first()
        assert saved is not None, "the record synced but no patient exists"
        assert saved.name == "Lakshmi Bai"      # decrypts back out
        assert saved.village == "Wagholi"
    finally:
        db.close()


def test_the_client_supplied_id_is_kept(client, auth):
    """Otherwise the visits queued against it have nothing to resolve to."""
    headers, worker_id = auth
    rec = _patient_record()
    client.post("/api/v1/sync/batch",
                json={"worker_id": worker_id, "records": [rec]}, headers=headers)
    db = SessionLocal()
    try:
        assert db.query(Patient).filter(Patient.patient_id == rec["patient_id"]).count() == 1
    finally:
        db.close()


def test_replaying_a_batch_does_not_duplicate_the_patient(client, auth):
    """The ordinary case on a connection that comes and goes. A duplicate
    carries its own visits, and then the two records disagree about her."""
    headers, worker_id = auth
    rec = _patient_record()
    body = {"worker_id": worker_id, "records": [rec]}
    client.post("/api/v1/sync/batch", json=body, headers=headers)
    r = client.post("/api/v1/sync/batch", json=body, headers=headers)
    assert r.json()["synced"] == 1, "the retry was reported as a failure"

    db = SessionLocal()
    try:
        assert db.query(Patient).filter(Patient.patient_id == rec["patient_id"]).count() == 1
    finally:
        db.close()


def test_patients_are_applied_before_visits_whatever_the_arrival_order(client, auth):
    """The visit is listed first, as a client queue ordered by time would
    send it if the ASHA registered and then immediately visited."""
    headers, worker_id = auth
    rec = _patient_record()
    visit = {
        "record_type": "visit",
        "patient_id": rec["patient_id"],
        "audio_base64": "",          # no audio: the visit is skipped, but only
        "language_code": "hi",       # after the patient reference would resolve
    }
    r = client.post("/api/v1/sync/batch",
                    json={"worker_id": worker_id, "records": [visit, rec]}, headers=headers)
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        assert db.query(Patient).filter(Patient.patient_id == rec["patient_id"]).first() is not None, (
            "the patient never got created, so the visit had nothing to attach to"
        )
    finally:
        db.close()


def test_a_nameless_patient_record_fails_that_record_only(client, auth):
    """One bad record must not take the rest of the morning with it."""
    headers, worker_id = auth
    good = _patient_record(name="Sarita")
    bad = _patient_record(name="")
    r = client.post("/api/v1/sync/batch",
                    json={"worker_id": worker_id, "records": [bad, good]}, headers=headers)
    body = r.json()
    assert body["synced"] == 1
    assert body["failed"] == 1

    db = SessionLocal()
    try:
        assert db.query(Patient).filter(Patient.patient_id == good["patient_id"]).first() is not None
    finally:
        db.close()


def test_an_unknown_record_type_is_queued_not_lost(client, auth):
    """It is not processed, but it is stored -- a record the server cannot
    apply yet should still be recoverable when it can."""
    headers, worker_id = auth
    r = client.post("/api/v1/sync/batch", json={
        "worker_id": worker_id,
        "records": [{"record_type": "household_survey", "payload": {"x": 1}}],
    }, headers=headers)
    assert r.status_code == 200

    from app.db.models.sync_queue import SyncQueueEntry
    db = SessionLocal()
    try:
        assert db.query(SyncQueueEntry).filter(
            SyncQueueEntry.record_type == "household_survey").count() >= 1
    finally:
        db.close()


def test_offline_registration_gets_the_same_identity_keys_as_an_online_one():
    """A woman registered with no signal is not a second-class record.

    The identity columns -- village code, the phone blind index, her
    sub-centre -- are what the duplicate check and every village lookup
    run on. Leaving them for backfill_identity() to fix on the next boot
    means that until somebody restarts the API she is invisible to both,
    so the colleague who registers her again tomorrow is not warned.
    """
    from app.services import identity

    client = TestClient(app)
    r = client.post("/api/v1/auth/login", json=DEMO_ASHA)
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    worker_id = r.json()["worker_id"]

    rch = _fresh_rch()
    # Spaced, the way it is printed on the MCP card.
    rch_typed = f"{rch[:4]} {rch[4:8]} {rch[8:]}"
    rec = _patient_record(
        name="Anjali Kadam",
        village="  wagholi  ",
        phone="9876500091",
        rch_number=rch_typed,
    )
    resp = client.post("/api/v1/sync/batch",
                       json={"worker_id": worker_id, "records": [rec]}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["synced"] == 1

    db = SessionLocal()
    try:
        saved = db.query(Patient).filter(Patient.patient_id == rec["patient_id"]).first()
        assert saved is not None
        assert saved.village_code == "WAGHOLI"
        assert saved.rch_number == rch
        assert saved.phone_hash == identity.phone_index("9876500091")
        assert saved.sub_centre_id is not None
    finally:
        db.close()


def test_a_bad_rch_number_does_not_cost_us_the_woman():
    """Typed wrong, days ago, on a phone with no signal.

    Dropping the number keeps the record; refusing it loses her -- and she
    is the part nobody can re-enter from memory. The ASHA corrects the
    number once the row is on her list.
    """
    client = TestClient(app)
    r = client.post("/api/v1/auth/login", json=DEMO_ASHA)
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    worker_id = r.json()["worker_id"]

    rec = _patient_record(name="Shobha More", rch_number="12345")
    resp = client.post("/api/v1/sync/batch",
                       json={"worker_id": worker_id, "records": [rec]}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["synced"] == 1

    db = SessionLocal()
    try:
        saved = db.query(Patient).filter(Patient.patient_id == rec["patient_id"]).first()
        assert saved is not None
        assert saved.name == "Shobha More"
        assert saved.rch_number is None
    finally:
        db.close()


def test_a_duplicate_rch_number_does_not_strand_the_rest_of_the_batch():
    """rch_number is unique. Somebody else registering the same woman while
    this phone was offline must not fail every other record queued behind
    her -- a batch can span several days of work."""
    client = TestClient(app)
    r = client.post("/api/v1/auth/login", json=DEMO_ASHA)
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    worker_id = r.json()["worker_id"]

    shared = _fresh_rch()
    first = _patient_record(name="Rekha Shinde", rch_number=shared)
    second = _patient_record(name="Rekha S", rch_number=shared)
    third = _patient_record(name="Vaishali Jadhav")

    resp = client.post(
        "/api/v1/sync/batch",
        json={"worker_id": worker_id, "records": [first, second, third]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["synced"] == 3

    db = SessionLocal()
    try:
        a = db.query(Patient).filter(Patient.patient_id == first["patient_id"]).first()
        b = db.query(Patient).filter(Patient.patient_id == second["patient_id"]).first()
        c = db.query(Patient).filter(Patient.patient_id == third["patient_id"]).first()
        assert a.rch_number == shared
        assert b is not None and b.rch_number is None
        assert c is not None  # the record behind the clash still landed
    finally:
        db.close()
