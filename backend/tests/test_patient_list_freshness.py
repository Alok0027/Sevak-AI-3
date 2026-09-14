"""A visit recorded a second ago must show on the patient list.

The ASHA reported this as three separate faults -- her patient list showed
no risk, the visit count stayed at zero, and she had to record the same
visit twice before the app admitted it existed. They were one fault: the
mobile app's three tabs live in an IndexedStack that never disposes them,
so each tab loaded once at login and never again. The list she was looking
at was the list as it stood before she recorded anything.

Recording a visit twice is not a cosmetic problem. It puts a duplicate
clinical record on a real patient, and on a HIGH visit it fires the
referral and the supervisor alert twice.

The mobile fix is a shared RefreshSignal in root_shell.dart. These tests
hold the other half still: that GET /patients/{worker_id} answers with the
new visit the moment it is written, so a stale screen is the only thing
that can ever be blamed for this again.
"""
import base64

from fastapi.testclient import TestClient

from app.main import app
from app.db.session import SessionLocal
from scripts.seed_synthetic_data import seed_demo_fixtures

# High BP and skipped iron tablets -- enough for the rules to return HIGH
# without asking a model anything.
HIGH_RISK_TRANSCRIPT = (
    "Kavita Rane, 26 saal, 8 mahine ki pregnancy. Aaj BP 160 over 110 tha. "
    "Usne pichle 2 hafte se iron tablets nahi li."
)


def _asha(client: TestClient) -> tuple[str, dict]:
    resp = client.post("/api/v1/auth/login", json={"phone": "9999999999", "pin": "1234"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["worker_id"], {"Authorization": f"Bearer {body['access_token']}"}


def _row(client: TestClient, worker_id: str, headers: dict, patient_id: str) -> dict:
    resp = client.get(f"/api/v1/patients/{worker_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return next(p for p in resp.json()["patients"] if p["id"] == patient_id)


def _record_visit(client: TestClient, worker_id: str, headers: dict, patient_id: str) -> dict:
    resp = client.post(
        "/api/v1/visits/voice",
        headers=headers,
        json={
            "worker_id": worker_id,
            "patient_id": patient_id,
            "audio_base64": base64.b64encode(HIGH_RISK_TRANSCRIPT.encode()).decode(),
            "language_code": "hi",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _new_patient(client: TestClient, headers: dict, name: str) -> str:
    resp = client.post(
        "/api/v1/patients",
        headers=headers,
        json={"name": name, "age": 26, "village": "Nashik", "pregnancy_stage": "8 months"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_a_freshly_registered_patient_reads_as_unvisited():
    """The baseline the ASHA sees before she records anything. Null risk
    and zero visits are correct here -- and are exactly what the stale
    screen kept showing afterwards, which is why this half is asserted."""
    with TestClient(app) as client:
        db = SessionLocal()
        try:
            seed_demo_fixtures(db)
        finally:
            db.close()
        worker_id, headers = _asha(client)
        patient_id = _new_patient(client, headers, "Freshness Baseline Patient")

        row = _row(client, worker_id, headers, patient_id)
        assert row["total_visits"] == 0
        assert row["risk_status"] is None
        assert row["last_visit"] is None


def test_list_shows_the_visit_immediately_after_it_is_recorded():
    with TestClient(app) as client:
        db = SessionLocal()
        try:
            seed_demo_fixtures(db)
        finally:
            db.close()
        worker_id, headers = _asha(client)
        patient_id = _new_patient(client, headers, "Freshness First Visit Patient")

        result = _record_visit(client, worker_id, headers, patient_id)
        assert result["risk_level"] == "HIGH"

        # No sync step, no delay, no second recording: the next read of the
        # list already carries it.
        row = _row(client, worker_id, headers, patient_id)
        assert row["total_visits"] == 1
        assert row["risk_status"] == "HIGH"
        assert row["last_visit"] is not None


def test_the_row_and_the_timeline_never_disagree():
    """What she saw: the patient's own screen showed the visits, the list
    said "no visits recorded yet". If those two endpoints can ever
    disagree, the app has no honest way to show her either."""
    with TestClient(app) as client:
        db = SessionLocal()
        try:
            seed_demo_fixtures(db)
        finally:
            db.close()
        worker_id, headers = _asha(client)
        patient_id = _new_patient(client, headers, "Freshness Agreement Patient")

        _record_visit(client, worker_id, headers, patient_id)
        _record_visit(client, worker_id, headers, patient_id)

        row = _row(client, worker_id, headers, patient_id)
        history = client.get(f"/api/v1/patients/{patient_id}/history", headers=headers)
        assert history.status_code == 200, history.text
        timeline = history.json()["visits"]

        assert row["total_visits"] == len(timeline) == 2
        # The list's risk is the newest visit's risk, not an older one.
        assert row["risk_status"] == timeline[0]["risk_level"]


def test_counts_are_per_patient_not_shared():
    """A patient with no visits must not inherit her neighbour's count --
    the grouped-count query is the kind of thing that silently starts
    reporting the whole worker's total."""
    with TestClient(app) as client:
        db = SessionLocal()
        try:
            seed_demo_fixtures(db)
        finally:
            db.close()
        worker_id, headers = _asha(client)
        visited = _new_patient(client, headers, "Freshness Visited Patient")
        untouched = _new_patient(client, headers, "Freshness Untouched Patient")

        _record_visit(client, worker_id, headers, visited)

        assert _row(client, worker_id, headers, visited)["total_visits"] == 1
        assert _row(client, worker_id, headers, untouched)["total_visits"] == 0
        assert _row(client, worker_id, headers, untouched)["risk_status"] is None


def test_an_offline_visit_counts_once_it_syncs():
    """The offline path is the one the ASHA is most likely to hit in the
    field, and the one where a stale list is most misleading: the visit
    exists on the phone, then on the server, and the row has to follow."""
    with TestClient(app) as client:
        db = SessionLocal()
        try:
            seed_demo_fixtures(db)
        finally:
            db.close()
        worker_id, headers = _asha(client)
        patient_id = _new_patient(client, headers, "Freshness Offline Patient")

        synced = client.post(
            "/api/v1/sync/batch",
            headers=headers,
            json={
                "worker_id": worker_id,
                "records": [
                    {
                        "record_type": "visit",
                        "patient_id": patient_id,
                        "audio_base64": base64.b64encode(HIGH_RISK_TRANSCRIPT.encode()).decode(),
                        "language_code": "hi",
                    }
                ],
            },
        )
        assert synced.status_code == 200, synced.text
        assert synced.json()["failed"] == 0

        row = _row(client, worker_id, headers, patient_id)
        assert row["total_visits"] == 1
        assert row["risk_status"] == "HIGH"
