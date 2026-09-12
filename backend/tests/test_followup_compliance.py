"""FR-08 accountability: which ASHA owes which patient a visit, and which
of those are late.

The analytics endpoint already counts done/pending/overdue, which tells a
supervisor something is wrong but not whose name to call. These cover the
row-level view that does.
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db.models.action import Action
from app.db.session import SessionLocal
from app.main import app
from app.services import followup_schedule


def _login(client: TestClient, phone: str, pin: str = "1234") -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_classify_uses_the_deadline_agent3_set():
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)

    assert followup_schedule.classify(now - timedelta(hours=5), now) == ("overdue", 5)
    assert followup_schedule.classify(now + timedelta(hours=3), now)[0] == "due_today"
    assert followup_schedule.classify(now + timedelta(days=4), now)[0] == "upcoming"
    assert followup_schedule.classify(None, now) == ("unscheduled", 0)


def test_hours_not_days_so_a_high_risk_miss_is_visible_immediately():
    """A HIGH-risk follow-up window is 48 hours. Rounding lateness to days
    would report a mother six hours past her deadline as '0 days late',
    which reads as fine when it is not."""
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    bucket, hours = followup_schedule.classify(now - timedelta(hours=6), now)
    assert bucket == "overdue"
    assert hours == 6
    assert followup_schedule.describe(bucket, hours) == "6h overdue"
    assert followup_schedule.describe("overdue", 72) == "3d overdue"


def test_compliance_lists_every_asha_including_those_with_nothing_due():
    """An absent row is ambiguous -- no work, or no data? 'Everyone else is
    clear' is itself what a supervisor is checking for."""
    with TestClient(app) as client:
        bmo = _login(client, "9999999902")
        resp = client.get(
            "/api/v1/dashboard/followup-compliance",
            headers={"Authorization": f"Bearer {bmo['access_token']}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["workers"], "no ASHA workers returned at all"
        names = [w["worker_name"] for w in body["workers"]]
        assert "Sunita Sharma" in names

        for worker in body["workers"]:
            assert worker["overdue"] == sum(1 for v in worker["visits"] if v["bucket"] == "overdue")
            assert worker["due_today"] == sum(1 for v in worker["visits"] if v["bucket"] == "due_today")


def test_an_overdue_followup_surfaces_against_its_worker():
    with TestClient(app) as client:
        bmo = _login(client, "9999999902")
        headers = {"Authorization": f"Bearer {bmo['access_token']}"}

        before = client.get("/api/v1/dashboard/followup-compliance", headers=headers).json()

        # Backdate one pending follow-up so it is unambiguously late.
        db = SessionLocal()
        try:
            action = (
                db.query(Action)
                .filter(Action.type == "followup", Action.status == "pending")
                .first()
            )
            assert action is not None, "seed data has no pending follow-up to age"
            # Deliberately far past every other deadline. The response is
            # collapsed to one row per patient showing her *most urgent*
            # follow-up, so a merely-3-days-late row could legitimately be
            # hidden behind a worse one for the same patient -- which would
            # make this test flaky rather than wrong.
            action.due_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=400)
            db.commit()
            aged_action_id = action.action_id
        finally:
            db.close()

        after = client.get("/api/v1/dashboard/followup-compliance", headers=headers).json()
        assert after["total_overdue"] >= before["total_overdue"]

        found = [
            v
            for w in after["workers"]
            for v in w["visits"]
            if v["action_id"] == aged_action_id
        ]
        assert found, "the aged follow-up did not appear in any worker's list"
        assert found[0]["bucket"] == "overdue"
        assert found[0]["hours_overdue"] >= 70
        assert found[0]["label"].endswith("d overdue")


def test_compliance_lists_each_patient_once_per_worker():
    """The table a BMO reads is one row per person, not per action row.

    Before this, an ASHA with 228 pending follow-ups against one patient
    produced 228 identical rows, which buried every other patient in the
    sub-centre and made the page look broken."""
    with TestClient(app) as client:
        bmo = _login(client, "9999999902")
        body = client.get(
            "/api/v1/dashboard/followup-compliance",
            headers={"Authorization": f"Bearer {bmo['access_token']}"},
        ).json()

        for w in body["workers"]:
            patient_ids = [v["patient_id"] for v in w["visits"]]
            assert len(patient_ids) == len(set(patient_ids)), (
                f"{w['worker_name']} has a patient listed more than once"
            )

            # The headline counts have to match the rows underneath them,
            # or a supervisor reading "228 overdue" above four names would
            # reasonably conclude the page was broken.
            assert w["overdue"] == sum(1 for v in w["visits"] if v["bucket"] == "overdue")
            assert w["due_today"] == sum(1 for v in w["visits"] if v["bucket"] == "due_today")
            assert w["upcoming"] == sum(1 for v in w["visits"] if v["bucket"] == "upcoming")

            # Nothing is dropped by the collapse: the rows plus the extras
            # they each carry account for every pending action.
            assert len(w["visits"]) + sum(v["also_pending"] for v in w["visits"]) == (
                w["total_pending_actions"]
            )


def test_asha_task_list_separates_today_from_upcoming():
    with TestClient(app) as client:
        asha = _login(client, "9999999999")
        resp = client.get(
            f"/api/v1/tasks/{asha['worker_id']}",
            headers={"Authorization": f"Bearer {asha['access_token']}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert set(body) == {"tasks", "today", "summary"}
        # Today's work is overdue + due today, never anything scheduled later.
        assert all(t["bucket"] in ("overdue", "due_today") for t in body["today"])

        due_now = [t for t in body["tasks"] if t["bucket"] in ("overdue", "due_today")]
        assert body["summary"]["overdue"] + body["summary"]["due_today"] == len(due_now)

        # ...but `today` is one row per *person*, not per action row. An
        # ASHA walks to a house, not to a follow-up: a patient with six
        # pending items is still one door, and listing her six times pushes
        # five other women off her screen.
        patient_ids = [t["patient_id"] for t in body["today"]]
        assert len(patient_ids) == len(set(patient_ids)), "today's list repeats a patient"
        assert set(patient_ids) == {t["patient_id"] for t in due_now}

        # Nothing is silently dropped: each row says how many other
        # follow-ups wait at the same door, and the rows plus their extras
        # add back up to every action that is due.
        assert len(body["today"]) + sum(t["also_pending"] for t in body["today"]) == len(due_now)

        # The reason shown is the most urgent one at that house.
        for row in body["today"]:
            same_patient = [t for t in due_now if t["patient_id"] == row["patient_id"]]
            soonest = min(t["due_at"] or "9999" for t in same_patient)
            assert (row["due_at"] or "9999") == soonest


def test_an_asha_cannot_read_the_compliance_view():
    with TestClient(app) as client:
        asha = _login(client, "9999999999")
        resp = client.get(
            "/api/v1/dashboard/followup-compliance",
            headers={"Authorization": f"Bearer {asha['access_token']}"},
        )
        assert resp.status_code == 403
