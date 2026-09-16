"""An ASHA goes away for a fortnight and names somebody to cover.

Cover, not transfer, and the distinction is the whole design.

A transfer is for somebody leaving the post: ownership moves, a supervisor
decides, it does not come back. Modelling a fortnight's leave that way
would be wrong three times over -- she would return to an empty list and
have to ask for her own village back, the colleague would find forty women
with no record of why or until when, and because a transfer needs an ANM,
leaving on Friday would need her ANM at a desk on Friday. The reliable
outcome of that last one is she tells a colleague verbally and the system
never hears about it, which is what happens today.

So ownership does not move. The colleague gains sight and the ability to
record, for a stated window, and it lapses on its own. That is what makes
it safe to let the ASHA arrange it herself.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_pin
from app.db.models.absence import WorkerAbsence
from app.db.models.patient import Patient
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.db.session import SessionLocal, backfill_identity
from app.main import app
from scripts.seed_synthetic_data import seed_demo_fixtures

SUB_CENTRE = "SC-PUNE-01"
TODAY = date.today()

AWAY = "9555200001"
COVERING = "9555200002"
ELSEWHERE = "9555200003"
BYSTANDER = "9555200004"


@pytest.fixture(autouse=True)
def _no_leave_left_over():
    """Start every test with nobody away.

    The suite shares one database, and the product refuses a second cover
    that overlaps an existing one -- correctly, because two people each
    believing the other is responsible is worse than nobody covering. That
    means leave declared by one test would make the next one fail on a
    guard rather than on the thing it is testing.
    """
    db = SessionLocal()
    try:
        db.query(WorkerAbsence).delete()
        db.commit()
    finally:
        db.close()
    yield


def _client() -> TestClient:
    client = TestClient(app)
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
        for phone, name, sub in (
            (AWAY, "Away Worker", SUB_CENTRE),
            (COVERING, "Covering Worker", SUB_CENTRE),
            (BYSTANDER, "Bystander Worker", SUB_CENTRE),
            (ELSEWHERE, "Faraway Worker", "SC-OTHER-04"),
        ):
            if db.query(Worker).filter(Worker.phone == phone).first() is None:
                db.add(Worker(name=name, phone=phone, pin_hash=hash_pin("1234"),
                              role="asha", sub_centre_id=sub))
        db.commit()
    finally:
        db.close()
    backfill_identity()
    return client


def _headers(client: TestClient, phone: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": "1234"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _wid(phone: str) -> str:
    db = SessionLocal()
    try:
        return db.query(Worker).filter(Worker.phone == phone).first().worker_id
    finally:
        db.close()


def _patient(client, headers, name, phone) -> str:
    resp = client.post("/api/v1/patients", headers=headers, json={"name": name, "phone": phone})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _declare(client, headers, covering_id, *, start=0, end=7) -> dict:
    return client.post(
        "/api/v1/workers/me/absence",
        headers=headers,
        json={
            "covering_worker_id": covering_id,
            "starts_on": str(TODAY + timedelta(days=start)),
            "ends_on": str(TODAY + timedelta(days=end)),
            "reason": "Family wedding in the next district.",
        },
    )


# ── The profile screen ──────────────────────────────────────────────────

def test_she_can_read_her_own_code():
    """The reason the profile exists. Her code is what she is asked for on
    a referral form; until now the only way to find it was to ask somebody
    with dashboard access, which is absurd for your own staff number."""
    with _client() as client:
        me = client.get("/api/v1/workers/me", headers=_headers(client, AWAY))
        assert me.status_code == 200, me.text
        body = me.json()
        assert body["worker_code"].startswith("ASHA-PUNE-01-")
        assert body["name"] == "Away Worker"
        assert body["sub_centre_id"] == SUB_CENTRE


def test_her_colleagues_are_the_other_ashas_in_her_sub_centre():
    with _client() as client:
        resp = client.get("/api/v1/workers/colleagues", headers=_headers(client, AWAY))
        assert resp.status_code == 200, resp.text
        names = {c["name"] for c in resp.json()}
        assert "Covering Worker" in names
        assert "Faraway Worker" not in names, "another sub-centre"
        assert "Away Worker" not in names, "herself"
        # Names and codes to pick from, not a staff directory.
        assert set(resp.json()[0]) == {"worker_id", "worker_code", "name"}


# ── What cover actually does ────────────────────────────────────────────

def test_her_patients_appear_on_the_covering_workers_list_named():
    with _client() as client:
        away_headers = _headers(client, AWAY)
        _patient(client, away_headers, "Covered Woman", "9876001001")

        declared = _declare(client, away_headers, _wid(COVERING))
        assert declared.status_code == 201, declared.text

        listed = client.get(
            f"/api/v1/patients/{_wid(COVERING)}", headers=_headers(client, COVERING)
        ).json()["patients"]
        covered = next(p for p in listed if p["name"] == "Covered Woman")
        # Named, not just flagged: she needs to know whose patient this is
        # and who to hand the story back to.
        assert covered["covering_for"] == "Away Worker"


def test_the_patient_never_stops_being_hers():
    """The difference from a transfer, asserted at the row."""
    with _client() as client:
        away_headers = _headers(client, AWAY)
        patient_id = _patient(client, away_headers, "Still Mine", "9876001002")
        _declare(client, away_headers, _wid(COVERING))

        db = SessionLocal()
        try:
            patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
            assert patient.worker_id == _wid(AWAY)
        finally:
            db.close()

        # And still on her own list, so she comes back to her own village.
        mine = client.get(f"/api/v1/patients/{_wid(AWAY)}", headers=away_headers).json()["patients"]
        assert any(p["name"] == "Still Mine" for p in mine)


def test_the_covering_worker_can_record_a_visit_and_it_is_hers():
    """The list and the visit endpoint have to agree. A list that shows a
    covered patient while recording refuses her is worse than no cover at
    all -- she walks to the house and then cannot write anything down."""
    import base64

    with _client() as client:
        away_headers = _headers(client, AWAY)
        patient_id = _patient(client, away_headers, "Visited While Away", "9876001003")
        _declare(client, away_headers, _wid(COVERING))

        transcript = "Aaj BP 118 over 76 tha. Dawa roz le rahi hai."
        resp = client.post(
            "/api/v1/visits/voice",
            headers=_headers(client, COVERING),
            json={
                "worker_id": _wid(COVERING),
                "patient_id": patient_id,
                "audio_base64": base64.b64encode(transcript.encode()).decode(),
                "language_code": "hi",
            },
        )
        assert resp.status_code == 200, resp.text

        db = SessionLocal()
        try:
            visit = db.query(Visit).filter(Visit.visit_id == resp.json()["visit_id"]).first()
            # Whoever walked to the house. Attributing it to the woman on
            # leave would put work on her accountability row that she did
            # not do.
            assert visit.worker_id == _wid(COVERING)
        finally:
            db.close()


def test_a_bystander_can_neither_see_nor_record():
    import base64

    with _client() as client:
        away_headers = _headers(client, AWAY)
        patient_id = _patient(client, away_headers, "Not Yours", "9876001004")
        _declare(client, away_headers, _wid(COVERING))

        bystander = _headers(client, BYSTANDER)
        listed = client.get(f"/api/v1/patients/{_wid(BYSTANDER)}", headers=bystander).json()["patients"]
        assert not any(p["name"] == "Not Yours" for p in listed)

        assert client.get(f"/api/v1/patients/{patient_id}/history", headers=bystander).status_code == 403

        resp = client.post(
            "/api/v1/visits/voice",
            headers=bystander,
            json={
                "worker_id": _wid(BYSTANDER),
                "patient_id": patient_id,
                "audio_base64": base64.b64encode(b"Aaj BP theek hai.").decode(),
                "language_code": "hi",
            },
        )
        assert resp.status_code == 403, resp.text


def test_a_visit_is_filed_against_the_signed_in_worker_whatever_the_payload_says():
    """The pipeline never checked, so an ASHA could post a visit under a
    colleague's name -- inflating that colleague's numbers on the
    accountability dashboard, or hiding her own workload behind them."""
    import base64

    with _client() as client:
        away_headers = _headers(client, AWAY)
        patient_id = _patient(client, away_headers, "Attribution Test", "9876001005")

        resp = client.post(
            "/api/v1/visits/voice",
            headers=away_headers,
            json={
                "worker_id": _wid(BYSTANDER),  # a lie
                "patient_id": patient_id,
                "audio_base64": base64.b64encode(b"Aaj BP 120 over 80 tha.").decode(),
                "language_code": "hi",
            },
        )
        assert resp.status_code == 200, resp.text

        db = SessionLocal()
        try:
            visit = db.query(Visit).filter(Visit.visit_id == resp.json()["visit_id"]).first()
            assert visit.worker_id == _wid(AWAY)
        finally:
            db.close()


# ── Limits ──────────────────────────────────────────────────────────────

def test_cover_must_be_someone_in_her_own_sub_centre():
    with _client() as client:
        resp = _declare(client, _headers(client, AWAY), _wid(ELSEWHERE))
        assert resp.status_code == 400, resp.text


def test_she_cannot_cover_for_herself():
    with _client() as client:
        resp = _declare(client, _headers(client, AWAY), _wid(AWAY))
        assert resp.status_code == 400, resp.text


def test_the_last_day_cannot_precede_the_first():
    with _client() as client:
        resp = client.post(
            "/api/v1/workers/me/absence",
            headers=_headers(client, AWAY),
            json={
                "covering_worker_id": _wid(COVERING),
                "starts_on": str(TODAY + timedelta(days=5)),
                "ends_on": str(TODAY),
            },
        )
        assert resp.status_code == 400, resp.text


def test_two_overlapping_covers_are_refused():
    """Two people each believing the other is responsible is worse than
    nobody covering -- at least then she knows."""
    with _client() as client:
        away_headers = _headers(client, AWAY)
        assert _declare(client, away_headers, _wid(COVERING)).status_code == 201
        second = _declare(client, away_headers, _wid(BYSTANDER), start=3, end=10)
        assert second.status_code == 409, second.text


def test_cover_cannot_be_handed_to_an_unapproved_account():
    with _client() as client:
        pending = client.post(
            "/api/v1/auth/register",
            json={"name": "Unapproved Cover", "phone": "9555200099", "pin": "3131",
                  "role": "asha", "sub_centre_id": SUB_CENTRE},
        ).json()
        resp = _declare(client, _headers(client, AWAY), pending["worker_id"])
        assert resp.status_code == 400, resp.text


def test_cover_that_has_not_started_yet_grants_nothing():
    """Booked for next month is not the same as away."""
    with _client() as client:
        away_headers = _headers(client, AWAY)
        _patient(client, away_headers, "Future Cover", "9876001006")
        assert _declare(client, away_headers, _wid(COVERING), start=30, end=40).status_code == 201

        listed = client.get(
            f"/api/v1/patients/{_wid(COVERING)}", headers=_headers(client, COVERING)
        ).json()["patients"]
        assert not any(p["name"] == "Future Cover" for p in listed)


def test_she_can_end_it_early_and_the_access_stops():
    with _client() as client:
        away_headers = _headers(client, AWAY)
        _patient(client, away_headers, "Early Return", "9876001007")
        absence = _declare(client, away_headers, _wid(COVERING)).json()

        ended = client.delete(
            f"/api/v1/workers/me/absence/{absence['absence_id']}", headers=away_headers
        )
        assert ended.status_code == 200, ended.text

        listed = client.get(
            f"/api/v1/patients/{_wid(COVERING)}", headers=_headers(client, COVERING)
        ).json()["patients"]
        assert not any(p["name"] == "Early Return" for p in listed)


def test_she_cannot_end_somebody_elses_leave():
    with _client() as client:
        absence = _declare(client, _headers(client, AWAY), _wid(COVERING)).json()
        resp = client.delete(
            f"/api/v1/workers/me/absence/{absence['absence_id']}",
            headers=_headers(client, BYSTANDER),
        )
        # Same answer as "no such absence", so this cannot be used to probe
        # other people's leave.
        assert resp.status_code == 404, resp.text


# ── The supervisor sees it ──────────────────────────────────────────────

def test_her_anm_can_see_who_is_away_and_who_is_carrying_them():
    """A supervisor finding out that half her block arranged cover between
    themselves and never told her is the failure this replaces."""
    with _client() as client:
        _declare(client, _headers(client, AWAY), _wid(COVERING))

        resp = client.get("/api/v1/workers/absences", headers=_headers(client, "9999999901"))
        assert resp.status_code == 200, resp.text
        rows = resp.json()["absences"]
        mine = next(a for a in rows if a["worker_name"] == "Away Worker")
        assert mine["covering_worker_name"] == "Covering Worker"
        assert mine["in_effect"] is True


def test_an_anm_sees_only_her_own_sub_centre():
    with _client() as client:
        # Somebody away in another sub-centre.
        db = SessionLocal()
        try:
            other = Worker(name="Other Cover", phone="9555200005", pin_hash=hash_pin("1234"),
                           role="asha", sub_centre_id="SC-OTHER-04")
            db.add(other)
            db.commit()
        finally:
            db.close()
        _declare(client, _headers(client, ELSEWHERE), _wid("9555200005"))
        _declare(client, _headers(client, AWAY), _wid(COVERING))

        rows = client.get(
            "/api/v1/workers/absences", headers=_headers(client, "9999999901")
        ).json()["absences"]
        names = {a["worker_name"] for a in rows}
        assert "Away Worker" in names
        assert "Faraway Worker" not in names


def test_an_asha_cannot_read_the_block_wide_absence_list():
    with _client() as client:
        assert client.get("/api/v1/workers/absences", headers=_headers(client, AWAY)).status_code == 403
