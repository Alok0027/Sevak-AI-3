"""Registering is a request, not an arrival.

SRS table 4 gives worker onboarding to the Admin panel and nothing else,
which is correct -- an ASHA is appointed to a post, she does not appoint
herself -- but it left no answer to "how does a new worker get an account
at all" except an admin typing her details from a phone call.

So: she registers, and an admin approves. The account row exists
immediately and cannot log in until a person has said yes.

The tests that matter here are the negative ones. A registration flow that
creates accounts is easy; one that reliably refuses to let an unapproved
account through is the entire point, and it has exactly one chokepoint --
login().
"""
from fastapi.testclient import TestClient

from app.db.models.worker import Worker
from app.db.session import SessionLocal
from app.main import app
from scripts.seed_synthetic_data import seed_demo_fixtures


def _client() -> TestClient:
    client = TestClient(app)
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
    finally:
        db.close()
    return client


def _headers(client: TestClient, phone: str, pin: str = "1234") -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _register(client: TestClient, phone: str, **overrides) -> dict:
    body = {
        "name": "Kavita Rane",
        "phone": phone,
        "pin": "7391",
        "role": "asha",
        "sub_centre_id": "SC-PUNE-01",
        "language_pref": "mr",
    }
    body.update(overrides)
    return client.post("/api/v1/auth/register", json=body)


def test_registering_creates_a_pending_account_and_no_token():
    with _client() as client:
        resp = _register(client, "9800000001")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "pending"
        # A stranger who filled in a form must not walk away holding a
        # credential for a health system.
        assert "access_token" not in body


def test_a_pending_account_cannot_log_in():
    with _client() as client:
        _register(client, "9800000002")
        resp = client.post("/api/v1/auth/login", json={"phone": "9800000002", "pin": "7391"})
        assert resp.status_code == 403, resp.text
        # Told apart from a wrong PIN on purpose: "invalid phone or PIN"
        # sends her to ring the block office about a PIN she typed right.
        assert "approval" in resp.json()["detail"].lower()


def test_an_approved_account_can_log_in():
    with _client() as client:
        registered = _register(client, "9800000003").json()
        admin = _headers(client, "9999999903")

        approved = client.post(
            f"/api/v1/admin/staff/{registered['worker_id']}/approve",
            headers=admin,
            json={"reason": "Rang the number; she is the ASHA for Wagholi."},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "active"
        assert approved.json()["approved_by_name"] == "Admin User"

        resp = client.post("/api/v1/auth/login", json={"phone": "9800000003", "pin": "7391"})
        assert resp.status_code == 200, resp.text


def test_a_rejected_account_cannot_log_in():
    with _client() as client:
        registered = _register(client, "9800000004").json()
        admin = _headers(client, "9999999903")
        client.post(
            f"/api/v1/admin/staff/{registered['worker_id']}/reject",
            headers=admin,
            json={"reason": "No such ASHA at this sub-centre; number belongs to someone else."},
        )
        resp = client.post("/api/v1/auth/login", json={"phone": "9800000004", "pin": "7391"})
        assert resp.status_code == 403, resp.text


def test_nobody_can_register_as_an_admin():
    """Admin creates every other account and reads the audit log. A system
    where anyone can register as one has no access control, only the
    appearance of it."""
    with _client() as client:
        resp = _register(client, "9800000005", role="admin")
        assert resp.status_code == 422, resp.text


def test_approving_is_not_open_to_everyone():
    """An ASHA cannot admit herself or a colleague, and a BMO has
    read-only access to individual records (SRS table 4).

    An ANM is deliberately absent from this list: she approves the ASHAs
    in her own sub-centre, which is the point of
    tests/test_anm_approves_her_own_ashas.py. She is the person who
    actually knows whether a woman claiming to be the ASHA for Wagholi is
    the ASHA for Wagholi.
    """
    with _client() as client:
        registered = _register(client, "9800000006").json()
        for phone in ("9999999999", "9999999902"):  # ASHA, BMO
            resp = client.post(
                f"/api/v1/admin/staff/{registered['worker_id']}/approve",
                headers=_headers(client, phone),
                json={},
            )
            assert resp.status_code == 403, phone


def test_rejecting_without_a_reason_is_refused():
    """Turning somebody away from a health-worker account is a decision the
    next admin -- and she, if she rings to ask -- deserves a reason for."""
    with _client() as client:
        registered = _register(client, "9800000007").json()
        admin = _headers(client, "9999999903")
        resp = client.post(
            f"/api/v1/admin/staff/{registered['worker_id']}/reject",
            headers=admin,
            json={"reason": "no"},
        )
        assert resp.status_code == 400, resp.text


def test_a_taken_phone_number_is_refused_without_saying_who_has_it():
    """The register form is open to the internet, which also makes it a way
    to ask the system which phone numbers belong to health workers."""
    with _client() as client:
        resp = _register(client, "9999999999")  # Sunita's number
        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"].lower()
        assert "sunita" not in detail
        assert "asha" not in detail


def test_every_existing_worker_stays_able_to_log_in():
    """The column that gates login arrived on a table that already had
    rows. If those rows had defaulted to anything but "active", this change
    would have locked out the entire district, including the only admin
    able to unlock it."""
    db = SessionLocal()
    try:
        statuses = {w.status for w in db.query(Worker).filter(Worker.role == "asha").all()}
    finally:
        db.close()
    assert statuses <= {"active", "pending", "rejected"}

    with _client() as client:
        for phone in ("9999999999", "9999999901", "9999999902", "9999999903"):
            resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": "1234"})
            assert resp.status_code == 200, f"{phone}: {resp.text}"


def test_a_short_or_non_numeric_pin_is_refused():
    with _client() as client:
        assert _register(client, "9800000008", pin="123").status_code == 422
        assert _register(client, "9800000009", pin="abcd").status_code == 422


def test_the_pending_queue_is_visible_to_an_admin():
    with _client() as client:
        _register(client, "9800000010")
        admin = _headers(client, "9999999903")
        resp = client.get("/api/v1/admin/staff?status=pending", headers=admin)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["pending_count"] >= 1
        assert all(s["status"] == "pending" for s in body["staff"])
        # The number she has to ring to check, right there on the row.
        assert any(s["phone"] == "9800000010" for s in body["staff"])
