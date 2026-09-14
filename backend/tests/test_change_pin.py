"""A worker must be able to change the PIN somebody else chose for her.

Every account starts with a PIN set by an admin or handed out at a block
meeting, and there was no way to change it. So "her" PIN was permanently
known to whoever set it, and a PIN shared across a sub-centre could never
be unshared. That is a worse hole than anything in the registration flow,
and it was invisible because nothing about it ever failed.
"""
from fastapi.testclient import TestClient

from app.db.models.audit_log import AuditLog
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


def _register_and_approve(client: TestClient, phone: str, pin: str) -> None:
    created = client.post(
        "/api/v1/auth/register",
        json={"name": "PIN Test Worker", "phone": phone, "pin": pin, "role": "asha"},
    )
    assert created.status_code == 201, created.text
    admin = client.post("/api/v1/auth/login", json={"phone": "9999999903", "pin": "1234"})
    headers = {"Authorization": f"Bearer {admin.json()['access_token']}"}
    approved = client.post(
        f"/api/v1/admin/staff/{created.json()['worker_id']}/approve", headers=headers, json={}
    )
    assert approved.status_code == 200, approved.text


def _token(client: TestClient, phone: str, pin: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_she_can_change_her_pin_and_the_old_one_stops_working():
    phone = "9700000001"
    with _client() as client:
        _register_and_approve(client, phone, "1357")
        headers = {"Authorization": f"Bearer {_token(client, phone, '1357')}"}

        changed = client.post(
            "/api/v1/auth/change-pin",
            headers=headers,
            json={"current_pin": "1357", "new_pin": "2468"},
        )
        assert changed.status_code == 204, changed.text

        assert client.post("/api/v1/auth/login", json={"phone": phone, "pin": "2468"}).status_code == 200
        assert client.post("/api/v1/auth/login", json={"phone": phone, "pin": "1357"}).status_code == 401


def test_the_current_pin_is_required():
    """Otherwise an unlocked phone left on a table is an account takeover."""
    phone = "9700000002"
    with _client() as client:
        _register_and_approve(client, phone, "1357")
        headers = {"Authorization": f"Bearer {_token(client, phone, '1357')}"}

        resp = client.post(
            "/api/v1/auth/change-pin",
            headers=headers,
            json={"current_pin": "9999", "new_pin": "2468"},
        )
        assert resp.status_code == 403, resp.text
        # And the real PIN still works -- a failed attempt must not lock
        # her out of her own account.
        assert client.post("/api/v1/auth/login", json={"phone": phone, "pin": "1357"}).status_code == 200


def test_the_new_pin_has_to_be_different():
    phone = "9700000003"
    with _client() as client:
        _register_and_approve(client, phone, "1357")
        headers = {"Authorization": f"Bearer {_token(client, phone, '1357')}"}
        resp = client.post(
            "/api/v1/auth/change-pin",
            headers=headers,
            json={"current_pin": "1357", "new_pin": "1357"},
        )
        assert resp.status_code == 400, resp.text


def test_a_signed_out_caller_cannot_change_anyones_pin():
    with _client() as client:
        resp = client.post(
            "/api/v1/auth/change-pin",
            json={"current_pin": "1234", "new_pin": "4321"},
        )
        assert resp.status_code in (401, 403)


def test_the_new_pin_never_reaches_the_audit_log():
    """Every admin can read the audit log. Writing the new PIN into it
    would make "change your PIN" a way of publishing it to them."""
    phone = "9700000004"
    with _client() as client:
        _register_and_approve(client, phone, "1357")
        headers = {"Authorization": f"Bearer {_token(client, phone, '1357')}"}
        client.post(
            "/api/v1/auth/change-pin",
            headers=headers,
            json={"current_pin": "1357", "new_pin": "8642"},
        )

    db = SessionLocal()
    try:
        entries = db.query(AuditLog).filter(AuditLog.action_type == "auth.change_pin").all()
        assert entries, "the change was not audited at all"
        for entry in entries:
            assert "8642" not in (entry.details or "")
            assert "1357" not in (entry.details or "")
    finally:
        db.close()
