"""GET/POST /api/v1/admin/staff and GET /api/v1/admin/audit-log -- the
admin panel's backend, all admin-only (require_roles("admin"))."""
from fastapi.testclient import TestClient

from app.db.models.worker import Worker
from app.db.session import SessionLocal
from app.main import app
from scripts.seed_synthetic_data import seed_demo_fixtures

NEW_WORKER_PHONE = "9888800001"


def _login(client: TestClient, phone: str, pin: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _remove_if_present(phone: str) -> None:
    # This suite runs against the shared dev DB across repeated runs (see
    # tests/test_api.py's docstring) -- a create-account test isn't
    # idempotent like seed_demo_fixtures, so clear out what a prior run
    # left behind before creating it again.
    db = SessionLocal()
    try:
        db.query(Worker).filter(Worker.phone == phone).delete()
        db.commit()
    finally:
        db.close()


def _seed():
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
    finally:
        db.close()


def test_non_admin_roles_are_forbidden_from_the_whole_admin_panel():
    with TestClient(app) as client:
        _seed()
        for phone in ("9999999999", "9999999901", "9999999902"):  # asha, anm, bmo
            user = _login(client, phone, "1234")
            headers = {"Authorization": f"Bearer {user['access_token']}"}
            assert client.get("/api/v1/admin/staff", headers=headers).status_code == 403
            assert client.get("/api/v1/admin/audit-log", headers=headers).status_code == 403


def test_admin_sees_staff_across_all_four_roles():
    with TestClient(app) as client:
        _seed()
        admin = _login(client, "9999999903", "1234")
        headers = {"Authorization": f"Bearer {admin['access_token']}"}
        resp = client.get("/api/v1/admin/staff", headers=headers)
        assert resp.status_code == 200, resp.text
        roles = {s["role"] for s in resp.json()["staff"]}
        # The ASHA-only roster (GET /api/v1/workers) can't show this --
        # that's the whole reason this endpoint exists.
        assert {"asha", "anm", "bmo", "admin"} <= roles


def test_admin_can_create_a_new_worker_who_can_then_log_in():
    with TestClient(app) as client:
        _seed()
        _remove_if_present(NEW_WORKER_PHONE)
        admin = _login(client, "9999999903", "1234")
        headers = {"Authorization": f"Bearer {admin['access_token']}"}
        resp = client.post(
            "/api/v1/admin/staff",
            headers=headers,
            json={
                "name": "Kavita Rane",
                "phone": NEW_WORKER_PHONE,
                "pin": "4321",
                "role": "asha",
                "sub_centre_id": "SC-PUNE-01",
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["role"] == "asha"

        new_login = _login(client, NEW_WORKER_PHONE, "4321")
        assert new_login["role"] == "asha"
        assert new_login["worker_name"] == "Kavita Rane"


def test_duplicate_phone_is_rejected():
    with TestClient(app) as client:
        _seed()
        admin = _login(client, "9999999903", "1234")
        headers = {"Authorization": f"Bearer {admin['access_token']}"}
        resp = client.post(
            "/api/v1/admin/staff",
            headers=headers,
            json={"name": "Duplicate", "phone": "9999999999", "pin": "1234", "role": "asha"},
        )
        assert resp.status_code == 409


def test_invalid_role_is_rejected():
    with TestClient(app) as client:
        _seed()
        admin = _login(client, "9999999903", "1234")
        headers = {"Authorization": f"Bearer {admin['access_token']}"}
        resp = client.post(
            "/api/v1/admin/staff",
            headers=headers,
            json={"name": "Someone", "phone": "9888800002", "pin": "1234", "role": "superuser"},
        )
        assert resp.status_code == 422


def test_audit_log_captures_a_successful_login():
    with TestClient(app) as client:
        _seed()
        _login(client, "9999999901", "1234")  # Dr. Rekha Joshi, SC-PUNE-01

        admin = _login(client, "9999999903", "1234")
        admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}
        resp = client.get(
            "/api/v1/admin/audit-log", headers=admin_headers, params={"action_type": "auth.login"}
        )
        assert resp.status_code == 200, resp.text
        entries = resp.json()["entries"]
        assert any(e["actor_name"] == "Dr. Rekha Joshi" and e["actor_role"] == "anm" for e in entries)


def test_failed_login_is_audited_with_no_actor_identity_leaked():
    with TestClient(app) as client:
        _seed()
        bad = client.post("/api/v1/auth/login", json={"phone": "9999999901", "pin": "0000"})
        assert bad.status_code == 401

        admin = _login(client, "9999999903", "1234")
        admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}
        resp = client.get(
            "/api/v1/admin/audit-log",
            headers=admin_headers,
            params={"action_type": "auth.login_failed"},
        )
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["entries"]) >= 1


def test_viewing_another_workers_record_is_audited():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        anm = _login(client, "9999999901", "1234")
        anm_headers = {"Authorization": f"Bearer {anm['access_token']}"}

        viewed = client.get(f"/api/v1/workers/{asha['worker_id']}/history", headers=anm_headers)
        assert viewed.status_code == 200, viewed.text

        admin = _login(client, "9999999903", "1234")
        admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}
        resp = client.get(
            "/api/v1/admin/audit-log", headers=admin_headers, params={"action_type": "worker.view"}
        )
        assert resp.status_code == 200
        assert any(e["record_id"] == asha["worker_id"] for e in resp.json()["entries"])
