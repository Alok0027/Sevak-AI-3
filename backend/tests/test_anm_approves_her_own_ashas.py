"""An ANM admits her own ASHAs. Nobody else's, and nobody senior.

Registration reached the point of working and then stalled: the queue was
admin-only, so a woman who signed up on her phone waited on a district
administrator who has never met her. The person who actually knows whether
the woman claiming to be the ASHA for Wagholi *is* the ASHA for Wagholi is
the ANM she would be working under.

The interesting tests here are the refusals. Letting an ANM approve is
easy; the whole value of the check is that she cannot reach past her own
sub-centre, and cannot promote anyone.
"""
from fastapi.testclient import TestClient

from app.core.security import hash_pin
from app.db.models.worker import Worker
from app.db.session import SessionLocal
from app.main import app
from scripts.seed_synthetic_data import seed_demo_fixtures

# Dr. Rekha Joshi (ANM) covers SC-PUNE-01 in the demo fixtures.
HER_SUB_CENTRE = "SC-PUNE-01"
OTHER_SUB_CENTRE = "SC-SHIRUR-07"


def _client() -> TestClient:
    client = TestClient(app)
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
        # An ANM for the other sub-centre, so "outside your scope" is a real
        # place with a real supervisor rather than an empty string.
        if db.query(Worker).filter(Worker.phone == "9555500002").first() is None:
            db.add(
                Worker(
                    name="Dr. Other ANM",
                    phone="9555500002",
                    pin_hash=hash_pin("1234"),
                    role="anm",
                    sub_centre_id=OTHER_SUB_CENTRE,
                )
            )
            db.commit()
    finally:
        db.close()
    return client


def _headers(client: TestClient, phone: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": "1234"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _register(client: TestClient, phone: str, role="asha", sub_centre=HER_SUB_CENTRE) -> str:
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "name": f"Applicant {phone[-4:]}",
            "phone": phone,
            "pin": "4682",
            "role": role,
            "sub_centre_id": sub_centre,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["worker_id"]


def test_an_anm_can_approve_an_asha_in_her_own_sub_centre():
    with _client() as client:
        worker_id = _register(client, "9555510001")
        anm = _headers(client, "9999999901")

        resp = client.post(
            f"/api/v1/admin/staff/{worker_id}/approve",
            headers=anm,
            json={"reason": "Rang her; she is the ASHA for Wagholi."},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "active"
        assert resp.json()["approved_by_name"] == "Dr. Rekha Joshi"

        # And she can now actually sign in, which is the only thing that
        # proves the approval did anything.
        login = client.post("/api/v1/auth/login", json={"phone": "9555510001", "pin": "4682"})
        assert login.status_code == 200, login.text


def test_an_anm_cannot_reach_into_another_sub_centre():
    with _client() as client:
        worker_id = _register(client, "9555510002", sub_centre=OTHER_SUB_CENTRE)
        anm = _headers(client, "9999999901")

        resp = client.post(f"/api/v1/admin/staff/{worker_id}/approve", headers=anm, json={})
        assert resp.status_code == 403, resp.text

        # Still locked out, which is the fact that matters.
        login = client.post("/api/v1/auth/login", json={"phone": "9555510002", "pin": "4682"})
        assert login.status_code == 403


def test_an_anm_cannot_approve_another_supervisor():
    """An ANM who could admit an ANM into a neighbouring sub-centre has
    granted herself the district."""
    with _client() as client:
        anm_applicant = _register(client, "9555510003", role="anm")
        bmo_applicant = _register(client, "9555510004", role="bmo")
        anm = _headers(client, "9999999901")

        for worker_id in (anm_applicant, bmo_applicant):
            resp = client.post(f"/api/v1/admin/staff/{worker_id}/approve", headers=anm, json={})
            assert resp.status_code == 403, resp.text


def test_an_admin_can_still_approve_anyone():
    with _client() as client:
        worker_id = _register(client, "9555510005", role="anm", sub_centre=OTHER_SUB_CENTRE)
        admin = _headers(client, "9999999903")
        resp = client.post(f"/api/v1/admin/staff/{worker_id}/approve", headers=admin, json={})
        assert resp.status_code == 200, resp.text


def test_the_queue_an_anm_sees_is_only_her_own():
    with _client() as client:
        mine = _register(client, "9555510006")
        theirs = _register(client, "9555510007", sub_centre=OTHER_SUB_CENTRE)
        senior = _register(client, "9555510008", role="anm")

        anm = _headers(client, "9999999901")
        resp = client.get("/api/v1/admin/registrations", headers=anm)
        assert resp.status_code == 200, resp.text
        ids = [s["worker_id"] for s in resp.json()["staff"]]

        assert mine in ids
        assert theirs not in ids
        assert senior not in ids
        assert resp.json()["pending_count"] == len(ids)


def test_the_queue_an_admin_sees_is_everyone():
    with _client() as client:
        mine = _register(client, "9555510009")
        theirs = _register(client, "9555510010", sub_centre=OTHER_SUB_CENTRE)

        admin = _headers(client, "9999999903")
        ids = [s["worker_id"] for s in client.get("/api/v1/admin/registrations", headers=admin).json()["staff"]]
        assert mine in ids and theirs in ids


def test_the_queue_is_oldest_first():
    """A queue that puts the newest arrival on top is a queue where the
    person who has waited longest is seen last."""
    with _client() as client:
        first = _register(client, "9555510011")
        second = _register(client, "9555510012")
        admin = _headers(client, "9999999903")
        ids = [s["worker_id"] for s in client.get("/api/v1/admin/registrations", headers=admin).json()["staff"]]
        assert ids.index(first) < ids.index(second)


def test_a_bmo_cannot_approve_anybody():
    """SRS table 4: a BMO has read-only access to individual records. The
    district view is for spotting problems, not for admitting staff."""
    with _client() as client:
        worker_id = _register(client, "9555510013")
        bmo = _headers(client, "9999999902")
        assert client.post(f"/api/v1/admin/staff/{worker_id}/approve", headers=bmo, json={}).status_code == 403
        assert client.get("/api/v1/admin/registrations", headers=bmo).status_code == 403


def test_an_asha_cannot_approve_herself():
    with _client() as client:
        worker_id = _register(client, "9555510014")
        asha = _headers(client, "9999999999")
        assert client.post(f"/api/v1/admin/staff/{worker_id}/approve", headers=asha, json={}).status_code == 403


def test_an_anm_can_reject_her_own_with_a_reason():
    with _client() as client:
        worker_id = _register(client, "9555510015")
        anm = _headers(client, "9999999901")

        thin = client.post(
            f"/api/v1/admin/staff/{worker_id}/reject", headers=anm, json={"reason": "no"}
        )
        assert thin.status_code == 400

        resp = client.post(
            f"/api/v1/admin/staff/{worker_id}/reject",
            headers=anm,
            json={"reason": "This number belongs to somebody else in the village."},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "rejected"


def test_an_anm_cannot_reject_outside_her_sub_centre():
    with _client() as client:
        worker_id = _register(client, "9555510016", sub_centre=OTHER_SUB_CENTRE)
        anm = _headers(client, "9999999901")
        resp = client.post(
            f"/api/v1/admin/staff/{worker_id}/reject",
            headers=anm,
            json={"reason": "Not one of mine, but I can see her anyway."},
        )
        assert resp.status_code == 403, resp.text


def test_the_staff_directory_stays_admin_only():
    """Widening approval must not have widened the district staff list. An
    ANM has no business reading every phone number in the block."""
    with _client() as client:
        anm = _headers(client, "9999999901")
        assert client.get("/api/v1/admin/staff", headers=anm).status_code == 403
