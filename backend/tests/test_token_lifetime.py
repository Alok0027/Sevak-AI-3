"""A day out of signal must not cost an ASHA her queued visits.

Every token lasted 8 hours. An ASHA who spent a working day in a village
with no bars came back to an expired one, and POST /sync/batch needs it --
so the visits she had recorded could not be pushed at all. The app showed
them stuck in the queue with no explanation and no way forward except
signing out and back in, which is not a step the offline story should ever
require and not one she would guess.

That made FR-07.1 ("the app shall function fully offline") and FR-01.3
("syncs within 30 seconds of connectivity") true only for workers who
happened to reconnect before lunch.

Supervisors keep the short session: they sign in to a dashboard, often on a
shared computer, and are online by definition.
"""
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import get_settings
from app.core.security import create_access_token, token_lifetime_minutes
from app.db.session import SessionLocal
from app.main import app
from scripts.seed_synthetic_data import seed_demo_fixtures


def _claims(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def _hours_valid(token: str) -> float:
    exp = datetime.fromtimestamp(_claims(token)["exp"], tz=timezone.utc)
    return (exp - datetime.now(timezone.utc)).total_seconds() / 3600


def test_an_asha_token_outlasts_a_long_offline_stretch():
    # The number that matters is "longer than any plausible gap between one
    # working day and the next time she has signal", not 30 days exactly.
    assert _hours_valid(create_access_token("w1", "asha")) > 24 * 7


def test_supervisor_tokens_stay_short():
    for role in ("anm", "bmo", "admin"):
        assert _hours_valid(create_access_token("w1", role)) <= 24, role


def test_the_two_lifetimes_are_not_accidentally_equal():
    """If someone sets FIELD_ROLES empty or the two settings converge, the
    bug comes back silently and every test above still passes on the
    supervisor side."""
    assert token_lifetime_minutes("asha") > token_lifetime_minutes("anm")


def test_refresh_returns_a_usable_token_for_the_same_worker():
    with TestClient(app) as client:
        db = SessionLocal()
        try:
            seed_demo_fixtures(db)
        finally:
            db.close()
        login = client.post("/api/v1/auth/login", json={"phone": "9999999999", "pin": "1234"})
        assert login.status_code == 200, login.text
        first = login.json()

        refreshed = client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": f"Bearer {first['access_token']}"},
        )
        assert refreshed.status_code == 200, refreshed.text
        body = refreshed.json()
        assert body["worker_id"] == first["worker_id"]
        assert body["role"] == first["role"]

        # The new token actually works on a guarded endpoint.
        me = client.get(
            f"/api/v1/patients/{body['worker_id']}",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert me.status_code == 200, me.text


def test_refresh_refuses_a_caller_with_no_token():
    with TestClient(app) as client:
        # 403 on older FastAPI, 401 on newer -- either is a refusal, and
        # pinning the exact one makes this test about the framework version
        # rather than about the endpoint being guarded.
        assert client.post("/api/v1/auth/refresh").status_code in (401, 403)


def test_refresh_refuses_a_garbage_token():
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401
