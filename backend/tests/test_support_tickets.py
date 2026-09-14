"""A problem reported from the Help screen has to reach a person.

The EOI deck names user adoption as the top delivery risk and "training &
onboarding" as the mitigation. Until now an ASHA whose microphone failed at
a doorstep had nowhere to say so: she abandoned the visit, wrote it in her
paper register, and nobody upstream ever learned the app had failed her.

These tests hold the loop closed at both ends -- she can file it, and an
admin sees it and can answer.
"""
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.models.support_ticket import SupportTicket
from app.db.session import SessionLocal, engine
from app.main import app
from scripts.seed_synthetic_data import seed_demo_fixtures


def _headers(client: TestClient, phone: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": "1234"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _client() -> TestClient:
    client = TestClient(app)
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
    finally:
        db.close()
    return client


def test_an_asha_can_report_a_problem_and_an_admin_sees_it():
    with _client() as client:
        asha = _headers(client, "9999999999")
        created = client.post(
            "/api/v1/support/tickets",
            headers=asha,
            json={
                "category": "microphone",
                "message": "Mic does not start recording after the update",
                "app_version": "1.0.0",
                "device_info": "iPhone 16e / iOS 26.3",
                "language": "hi",
            },
        )
        assert created.status_code == 201, created.text
        ticket_id = created.json()["ticket_id"]
        assert created.json()["status"] == "open"

        admin = _headers(client, "9999999903")
        listed = client.get("/api/v1/support/tickets", headers=admin)
        assert listed.status_code == 200, listed.text
        ids = [t["ticket_id"] for t in listed.json()["tickets"]]
        assert ticket_id in ids

        mine = next(t for t in listed.json()["tickets"] if t["ticket_id"] == ticket_id)
        # The admin can ring her back without looking anyone up.
        assert mine["worker_name"] == "Sunita Sharma"
        assert mine["worker_phone"] == "9999999999"
        assert mine["device_info"] == "iPhone 16e / iOS 26.3"


def test_the_message_is_encrypted_at_rest():
    """She will put patient names in here -- "recording Pallavi's BP keeps
    failing" is a patient name in a support ticket. NFR-SC1 applies to
    every free-text field she can type into, not just the clinical ones."""
    secret = "Pallavi Singh ka BP record nahi ho raha"
    with _client() as client:
        asha = _headers(client, "9999999999")
        created = client.post(
            "/api/v1/support/tickets",
            headers=asha,
            json={"category": "microphone", "message": secret},
        )
        assert created.status_code == 201, created.text
        ticket_id = created.json()["ticket_id"]

    # text() with a bound parameter, not the ORM and not Table.select():
    # both of those run the column's TypeDecorator on the way out, so they
    # hand back the decrypted string and the assertion below would pass
    # against a table storing plaintext.
    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT message FROM support_tickets WHERE ticket_id = :tid"),
            {"tid": ticket_id},
        ).scalar_one()
    assert secret not in stored
    assert stored.startswith("enc:")

    db = SessionLocal()
    try:
        # ...and it still reads back correctly through the ORM.
        ticket = db.query(SupportTicket).filter(SupportTicket.ticket_id == ticket_id).first()
        assert ticket.message == secret
    finally:
        db.close()


def test_a_supervisor_cannot_read_her_tickets():
    """"The app does not work" routed to the person who rates her
    performance is a good way to make sure it is never reported."""
    with _client() as client:
        asha = _headers(client, "9999999999")
        client.post(
            "/api/v1/support/tickets",
            headers=asha,
            json={"category": "sync", "message": "Visits stuck in the queue all day"},
        )
        for phone in ("9999999901", "9999999902"):  # ANM, BMO
            resp = client.get("/api/v1/support/tickets", headers=_headers(client, phone))
            assert resp.status_code == 403, phone


def test_she_can_see_her_own_tickets_and_the_answer():
    with _client() as client:
        asha = _headers(client, "9999999999")
        created = client.post(
            "/api/v1/support/tickets",
            headers=asha,
            json={"category": "login", "message": "PIN not accepted since yesterday"},
        )
        ticket_id = created.json()["ticket_id"]

        admin = _headers(client, "9999999903")
        resolved = client.post(
            f"/api/v1/support/tickets/{ticket_id}/resolve",
            headers=admin,
            json={"note": "PIN reset from the admin panel. Try 1234 and change it."},
        )
        assert resolved.status_code == 200, resolved.text

        mine = client.get("/api/v1/support/tickets/mine", headers=asha)
        assert mine.status_code == 200, mine.text
        ticket = next(t for t in mine.json()["tickets"] if t["ticket_id"] == ticket_id)
        assert ticket["status"] == "resolved"
        assert "PIN reset" in ticket["resolution_note"]


def test_one_workers_tickets_are_not_visible_to_another():
    with _client() as client:
        asha = _headers(client, "9999999999")
        created = client.post(
            "/api/v1/support/tickets",
            headers=asha,
            json={"category": "other", "message": "Something private about my phone"},
        )
        ticket_id = created.json()["ticket_id"]

        anm = _headers(client, "9999999901")
        mine = client.get("/api/v1/support/tickets/mine", headers=anm)
        assert mine.status_code == 200, mine.text
        assert ticket_id not in [t["ticket_id"] for t in mine.json()["tickets"]]


def test_she_is_given_somebody_to_ring():
    """An ASHA stuck at a doorstep needs a number, not a form. The ANM
    covering her sub-centre changes, so this comes from the server rather
    than being typed into a release."""
    with _client() as client:
        resp = client.get("/api/v1/support/contacts", headers=_headers(client, "9999999999"))
        assert resp.status_code == 200, resp.text
        contacts = resp.json()["contacts"]
        by_rel = {c["relationship"]: c for c in contacts}

        # Sunita is in SC-PUNE-01, which Dr. Rekha Joshi covers.
        assert by_rel["anm"]["name"] == "Dr. Rekha Joshi"
        assert by_rel["anm"]["phone"] == "9999999901"
        # And the block office either way.
        assert by_rel["block_office"]["phone"] == "9999999902"


def test_a_worker_with_no_anm_still_has_somebody_to_call():
    """A sub-centre with no ANM on record is a data gap, not a reason to
    show her an empty Help screen."""
    from app.db.models.worker import Worker

    db = SessionLocal()
    try:
        orphan = Worker(
            name="Unattached ASHA",
            phone="9111100001",
            pin_hash=__import__("app.core.security", fromlist=["hash_pin"]).hash_pin("1234"),
            role="asha",
            sub_centre_id="SC-NO-ANM-01",
        )
        db.add(orphan)
        db.commit()
    finally:
        db.close()

    with _client() as client:
        resp = client.get("/api/v1/support/contacts", headers=_headers(client, "9111100001"))
        assert resp.status_code == 200, resp.text
        rels = {c["relationship"] for c in resp.json()["contacts"]}
        assert "anm" not in rels
        assert "block_office" in rels


def test_an_unknown_category_is_filed_not_rejected():
    """An app build offering a new category must not have its reports
    bounced by an older server. Losing the report is worse than filing it
    under 'other'."""
    with _client() as client:
        asha = _headers(client, "9999999999")
        created = client.post(
            "/api/v1/support/tickets",
            headers=asha,
            json={"category": "bluetooth-printer", "message": "Cannot print the referral slip"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["category"] == "other"


def test_resolving_twice_is_refused():
    with _client() as client:
        asha = _headers(client, "9999999999")
        ticket_id = client.post(
            "/api/v1/support/tickets",
            headers=asha,
            json={"category": "sync", "message": "Queue badge stuck at 3"},
        ).json()["ticket_id"]

        admin = _headers(client, "9999999903")
        note = {"note": "Cleared the stale queue rows on the server."}
        assert client.post(f"/api/v1/support/tickets/{ticket_id}/resolve", headers=admin, json=note).status_code == 200
        assert client.post(f"/api/v1/support/tickets/{ticket_id}/resolve", headers=admin, json=note).status_code == 400


def test_a_resolution_needs_an_actual_note():
    """These tickets are the only record of what the app does to people in
    the field. "done" tells the next person nothing."""
    with _client() as client:
        asha = _headers(client, "9999999999")
        ticket_id = client.post(
            "/api/v1/support/tickets",
            headers=asha,
            json={"category": "other", "message": "App closes when I open Follow-ups"},
        ).json()["ticket_id"]

        admin = _headers(client, "9999999903")
        resp = client.post(
            f"/api/v1/support/tickets/{ticket_id}/resolve", headers=admin, json={"note": "ok"}
        )
        assert resp.status_code == 422
