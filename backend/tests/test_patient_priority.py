"""Who the list puts first.

Colour already said *what* a patient is. Nothing said *when*. A HIGH-risk
mother at row 47 of sixty was correctly coloured and still missed, because
a list with no opinion about order asks its reader to hold the whole ward
in their head and pick.

These tests pin the opinion. Most of them are orderings rather than
numbers, on purpose: the exact scores are an implementation detail nobody
should depend on, but "an overdue HIGH comes before a HIGH seen today"
is a clinical claim the product makes, and it should fail loudly if
somebody tunes a constant and quietly inverts it.
"""
import base64
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db.models.action import Action
from app.db.models.visit import Visit
from app.db.session import SessionLocal
from app.main import app
from app.services import patient_priority
from scripts.seed_synthetic_data import seed_demo_fixtures

NOW = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)


def _score(risk, *, due_in_hours=None, open_followup=True):
    due = NOW + timedelta(hours=due_in_hours) if due_in_hours is not None else None
    return patient_priority.assess(
        risk, due, has_open_followup=open_followup and due is not None, now=NOW
    )


# ── The orderings the product claims ────────────────────────────────────

def test_high_outranks_everything_that_is_not_late():
    high = _score("HIGH", open_followup=False).score
    for risk in ("MEDIUM", "LOW", "UNASSESSED", None):
        assert high > _score(risk, open_followup=False).score, risk


def test_lateness_escalates_within_a_risk_level():
    on_time = _score("MEDIUM", due_in_hours=48).score
    due_today = _score("MEDIUM", due_in_hours=2).score
    late = _score("MEDIUM", due_in_hours=-48).score
    later = _score("MEDIUM", due_in_hours=-24 * 6).score
    assert on_time < due_today < late < later


def test_an_overdue_low_does_not_outrank_a_high():
    """Her thirty-day window was generous precisely because she is well.
    Agent 3 already weighted the deadline by risk, so letting lateness
    outrank severity would weight it twice."""
    assert _score("LOW", due_in_hours=-24 * 10).score < _score("HIGH", open_followup=False).score


def test_an_overdue_high_outranks_a_high_seen_this_morning():
    assert _score("HIGH", due_in_hours=-72).score > _score("HIGH", due_in_hours=72).score


def test_unassessed_sits_between_medium_and_high():
    """Not a fourth grade of illness -- it means nobody knows how she is.
    An unknown outranks a mild known finding, and loses to a measured
    emergency."""
    assert (
        _score("MEDIUM", open_followup=False).score
        < _score("UNASSESSED", open_followup=False).score
        < _score("HIGH", open_followup=False).score
    )


def test_a_very_old_lapse_does_not_bury_this_week():
    """Past a fortnight the list stops being a schedule and becomes a
    backlog. A patient missed for three months must not outrank a HIGH
    mother flagged an hour ago."""
    ancient = _score("LOW", due_in_hours=-24 * 90).score
    assert ancient < _score("HIGH", open_followup=False).score


# ── "Today's work" is a different question from "how bad" ───────────────

def test_todays_work_is_high_or_owed():
    assert _score("HIGH", open_followup=False).needs_attention
    assert _score("LOW", due_in_hours=-24).needs_attention, "an overdue promise is still a promise"
    assert _score("MEDIUM", due_in_hours=2).needs_attention
    assert not _score("MEDIUM", due_in_hours=24 * 5).needs_attention
    assert not _score("LOW", open_followup=False).needs_attention
    assert not _score(None, open_followup=False).needs_attention


def test_a_completed_followup_is_not_a_debt():
    """Done is done, however late the date on it has since become."""
    assert not _score("MEDIUM", due_in_hours=-24 * 30, open_followup=False).needs_attention


def test_a_high_with_nothing_late_still_names_itself():
    assert _score("HIGH", open_followup=False).reason == patient_priority.HIGH_RISK


def test_lateness_wins_the_label_over_severity():
    """A HIGH that is also three days late should say "overdue" -- the
    severity tag beside it is already saying HIGH, and a row that says the
    same thing twice teaches the reader to skim one of them."""
    assert _score("HIGH", due_in_hours=-72).reason == patient_priority.OVERDUE


def test_a_quiet_patient_has_no_reason_at_all():
    quiet = _score("LOW", open_followup=False)
    assert quiet.reason is None and not quiet.needs_attention


# ── End to end, through the endpoint an ASHA actually reads ─────────────

HIGH_TRANSCRIPT = (
    "Kavita Rane, 26 saal, 8 mahine ki pregnancy. Aaj BP 165 over 112 tha. "
    "Usne pichle 2 hafte se iron tablets nahi li."
)
CALM_TRANSCRIPT = "Sunita Devi, 30 saal. Aaj BP 112 over 74 tha. Dawa roz le rahi hai."


def _client() -> TestClient:
    client = TestClient(app)
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
    finally:
        db.close()
    return client


def _asha(client):
    body = client.post("/api/v1/auth/login", json={"phone": "9999999999", "pin": "1234"}).json()
    return body["worker_id"], {"Authorization": f"Bearer {body['access_token']}"}


def _patient(client, headers, name):
    resp = client.post("/api/v1/patients", headers=headers, json={"name": name, "age": 26})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _visit(client, worker_id, headers, patient_id, transcript):
    resp = client.post(
        "/api/v1/visits/voice",
        headers=headers,
        json={
            "worker_id": worker_id,
            "patient_id": patient_id,
            "audio_base64": base64.b64encode(transcript.encode()).decode(),
            "language_code": "hi",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_list_puts_the_high_risk_patient_first():
    """The whole point, asserted against the endpoint rather than the
    scoring function: a HIGH mother registered last must not be last."""
    with _client() as client:
        worker_id, headers = _asha(client)
        calm = _patient(client, headers, "Zzz Calm Patient")
        _visit(client, worker_id, headers, calm, CALM_TRANSCRIPT)
        urgent = _patient(client, headers, "Zzz Urgent Patient")
        _visit(client, worker_id, headers, urgent, HIGH_TRANSCRIPT)

        rows = client.get(f"/api/v1/patients/{worker_id}", headers=headers).json()
        ids = [p["id"] for p in rows["patients"]]
        assert ids.index(urgent) < ids.index(calm)

        row = next(p for p in rows["patients"] if p["id"] == urgent)
        assert row["needs_attention"] is True
        assert row["attention_reason"] in ("high_risk", "overdue", "due_today")
        assert rows["attention_count"] >= 1


def test_an_overdue_followup_lifts_a_patient_above_a_calmer_one():
    with _client() as client:
        worker_id, headers = _asha(client)
        calm = _patient(client, headers, "Zzz Steady Patient")
        _visit(client, worker_id, headers, calm, CALM_TRANSCRIPT)
        lapsed = _patient(client, headers, "Zzz Lapsed Patient")
        result = _visit(client, worker_id, headers, lapsed, CALM_TRANSCRIPT)

        # Backdate her follow-up so it is genuinely missed.
        db = SessionLocal()
        try:
            visit = db.query(Visit).filter(Visit.visit_id == result["visit_id"]).first()
            action = (
                db.query(Action)
                .filter(Action.visit_id == visit.visit_id, Action.type == "followup")
                .first()
            )
            action.due_at = datetime.now(timezone.utc) - timedelta(days=4)
            action.status = "pending"
            db.commit()
        finally:
            db.close()

        rows = client.get(f"/api/v1/patients/{worker_id}", headers=headers).json()["patients"]
        ids = [p["id"] for p in rows]
        assert ids.index(lapsed) < ids.index(calm)

        row = next(p for p in rows if p["id"] == lapsed)
        assert row["attention_reason"] == "overdue"
        assert row["hours_overdue"] >= 24 * 3


def test_the_order_is_stable_between_two_identical_reads():
    """A list that reorders under her thumb is a list she stops trusting.
    Ties break on name, so two refreshes agree."""
    with _client() as client:
        worker_id, headers = _asha(client)
        for name in ("Zzz Stable A", "Zzz Stable B", "Zzz Stable C"):
            _patient(client, headers, name)

        first = [p["id"] for p in client.get(f"/api/v1/patients/{worker_id}", headers=headers).json()["patients"]]
        second = [p["id"] for p in client.get(f"/api/v1/patients/{worker_id}", headers=headers).json()["patients"]]
        assert first == second


def test_the_supervisor_directory_is_ordered_the_same_way():
    """An ANM and the ASHA she supervises reading differently-ordered
    copies of the same ward is how a dashboard stops being trusted."""
    with _client() as client:
        worker_id, headers = _asha(client)
        calm = _patient(client, headers, "Zzz Directory Calm")
        _visit(client, worker_id, headers, calm, CALM_TRANSCRIPT)
        urgent = _patient(client, headers, "Zzz Directory Urgent")
        _visit(client, worker_id, headers, urgent, HIGH_TRANSCRIPT)

        anm = client.post("/api/v1/auth/login", json={"phone": "9999999901", "pin": "1234"}).json()
        directory = client.get(
            "/api/v1/patients", headers={"Authorization": f"Bearer {anm['access_token']}"}
        ).json()
        ids = [p["id"] for p in directory["patients"]]
        assert ids.index(urgent) < ids.index(calm)
        assert directory["attention_count"] >= 1


def test_a_patient_with_no_visits_does_not_claim_attention():
    """Registered and never seen is a gap worth closing, but it is not a
    clinical finding, and dressing it as one would put a name nobody has
    assessed above a mother who is actually unwell."""
    with _client() as client:
        worker_id, headers = _asha(client)
        fresh = _patient(client, headers, "Zzz Never Visited")
        rows = client.get(f"/api/v1/patients/{worker_id}", headers=headers).json()["patients"]
        row = next(p for p in rows if p["id"] == fresh)
        assert row["needs_attention"] is False
        assert row["attention_reason"] is None
