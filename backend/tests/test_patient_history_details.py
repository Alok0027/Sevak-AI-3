"""GET /api/v1/patients/{patient_id}/history must carry the registration
record, not just the visit timeline.

An ASHA opens this standing at a door. She needs the age and village to
be sure she has the right house, the phone number to ring if nobody
answers, and the baseline BP and blood sugar to compare today's reading
against -- before any of the history is useful. Returning only a name and
a list of visits made the mobile screen guess or omit all of that."""
from fastapi.testclient import TestClient

from app.main import app

BASELINE_FIELDS = {
    "gender",
    "phone",
    "bp_systolic",
    "bp_diastolic",
    "blood_sugar_fasting",
    "blood_sugar_random",
    "registered_at",
}


def _login(client: TestClient, phone: str, pin: str = "1234") -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_history_returns_the_whole_registration_record():
    with TestClient(app) as client:
        asha = _login(client, "9999999999")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}

        created = client.post(
            "/api/v1/patients",
            headers=headers,
            json={
                "name": "Kamla Devi",
                "age": 34,
                "gender": "female",
                "village": "Wagholi",
                "phone": "9876543210",
                "pregnancy_stage": "5 months",
                "bp_systolic": 132,
                "bp_diastolic": 86,
                "blood_sugar_fasting": 104,
                "blood_sugar_random": 155,
            },
        )
        assert created.status_code == 201, created.text
        patient_id = created.json()["id"]

        body = client.get(f"/api/v1/patients/{patient_id}/history", headers=headers).json()

        assert BASELINE_FIELDS <= set(body), "history is missing registration fields"
        assert body["patient_name"] == "Kamla Devi"
        assert body["age"] == 34
        assert body["gender"] == "female"
        assert body["village"] == "Wagholi"
        assert body["phone"] == "9876543210"
        assert body["pregnancy_stage"] == "5 months"
        assert (body["bp_systolic"], body["bp_diastolic"]) == (132, 86)
        assert body["blood_sugar_fasting"] == 104
        assert body["blood_sugar_random"] == 155
        assert body["registered_at"] is not None
        # Newly registered: the timeline is legitimately empty, and that
        # must not look like a failure to the app.
        assert body["visits"] == []


def test_unfilled_baselines_come_back_null_not_zero():
    """Registration only requires a name. A missing blood pressure has to
    arrive as null so the screen can say 'not recorded' -- a 0/0 would
    read as a real, alarming measurement."""
    with TestClient(app) as client:
        asha = _login(client, "9999999999")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}

        created = client.post("/api/v1/patients", headers=headers, json={"name": "Asha Test"})
        assert created.status_code == 201, created.text
        body = client.get(
            f"/api/v1/patients/{created.json()['id']}/history", headers=headers
        ).json()

        for field in BASELINE_FIELDS - {"registered_at"}:
            assert body[field] is None, f"{field} should be null when never recorded"
        assert body["registered_at"] is not None
