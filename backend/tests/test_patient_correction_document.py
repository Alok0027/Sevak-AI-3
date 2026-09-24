"""Correcting a name, and the 24-hour line between a typo and a record.

An ASHA mishears "Meera" as "Heera" at the door. On the day, that is a
typo and she fixes it. A month later the same edit is a different act:
a referral letter has gone to a PHC under that name and an HMIS return
has counted her under it, so changing it is a correction to a record the
district has already reported on -- the BMO makes it, against a document.
"""
import io
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db.models.audit_log import AuditLog
from app.db.models.correction_document import CorrectionDocument
from app.db.models.patient import Patient
from app.db.session import SessionLocal
from app.main import app
from scripts.seed_synthetic_data import seed_demo_fixtures


def _login(client, phone, pin="1234"):
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _new_patient(client, headers, name="Heera Patil"):
    resp = client.post("/api/v1/patients", headers=headers,
                       json={"name": name, "age": 28, "gender": "female", "village": "Wagholi"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _age_patient(patient_id, days):
    """Backdate registration, to put the record either side of the line."""
    db = SessionLocal()
    try:
        p = db.get(Patient, patient_id)
        p.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        db.commit()
    finally:
        db.close()


def _seed():
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
    finally:
        db.close()


def _document(name="aadhaar.jpg", content=b"\xff\xd8\xff" + b"scan" * 100):
    return {"document": (name, io.BytesIO(content), "image/jpeg")}


# ── The first day: a typo ────────────────────────────────────────────────

def test_the_asha_can_fix_her_own_typo_on_the_day():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        pid = _new_patient(client, headers)

        resp = client.patch(f"/api/v1/patients/{pid}", headers=headers,
                            json={"name": "Meera Patil", "reason": "Misheard at the door."})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Meera Patil"


# ── After a day: a record ────────────────────────────────────────────────

def test_after_24_hours_the_asha_is_refused_and_told_why():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        pid = _new_patient(client, headers)
        _age_patient(pid, days=3)

        resp = client.patch(f"/api/v1/patients/{pid}", headers=headers,
                            json={"name": "Meera Patil", "reason": "Fixing the spelling."})
        assert resp.status_code == 409
        # The refusal has to say what to do instead, or it is just a wall.
        assert "Block Medical Officer" in resp.json()["detail"]
        assert "document" in resp.json()["detail"].lower()


def test_the_anm_is_refused_the_same_way():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999")
        pid = _new_patient(client, {"Authorization": f"Bearer {asha['access_token']}"})
        _age_patient(pid, days=3)

        anm = _login(client, "9999999901")
        resp = client.patch(f"/api/v1/patients/{pid}",
                            headers={"Authorization": f"Bearer {anm['access_token']}"},
                            json={"name": "Meera Patil", "reason": "Correcting the register."})
        assert resp.status_code == 409


def test_the_bmo_corrects_it_with_a_document():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999")
        pid = _new_patient(client, {"Authorization": f"Bearer {asha['access_token']}"})
        _age_patient(pid, days=40)

        bmo = _login(client, "9999999902")
        headers = {"Authorization": f"Bearer {bmo['access_token']}"}
        resp = client.post(
            f"/api/v1/patients/{pid}/correction",
            headers=headers,
            data={"name": "Meera Patil", "reason": "Aadhaar card produced by the family."},
            files=_document(),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Meera Patil"

        db = SessionLocal()
        try:
            doc = db.query(CorrectionDocument).filter(
                CorrectionDocument.patient_id == pid).one()
            assert doc.filename == "aadhaar.jpg"
            assert doc.size_bytes > 0
            assert doc.content.startswith(b"\xff\xd8\xff"), "the file is stored as handed over"
            assert doc.uploaded_by_name == "Dr. Vikram Rao"

            entry = db.query(AuditLog).filter(
                AuditLog.action_type == "patient.correct.official",
                AuditLog.record_id == pid).one()
            assert doc.document_id in entry.details
            # The old name must not be written into a log the admin console shows.
            assert "Heera Patil" not in entry.details
        finally:
            db.close()


def test_a_correction_without_a_document_is_refused():
    """The document is the point of the endpoint, not a nice-to-have."""
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999")
        pid = _new_patient(client, {"Authorization": f"Bearer {asha['access_token']}"})
        _age_patient(pid, days=40)

        bmo = _login(client, "9999999902")
        resp = client.post(f"/api/v1/patients/{pid}/correction",
                           headers={"Authorization": f"Bearer {bmo['access_token']}"},
                           data={"name": "Meera Patil", "reason": "No paperwork to hand."})
        assert resp.status_code == 422


def test_a_document_over_5mb_is_refused_with_its_size():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999")
        pid = _new_patient(client, {"Authorization": f"Bearer {asha['access_token']}"})
        _age_patient(pid, days=40)

        bmo = _login(client, "9999999902")
        oversized = b"x" * (5 * 1024 * 1024 + 1)
        resp = client.post(f"/api/v1/patients/{pid}/correction",
                           headers={"Authorization": f"Bearer {bmo['access_token']}"},
                           data={"name": "Meera Patil", "reason": "A very large scan."},
                           files=_document("scan.pdf", oversized))
        assert resp.status_code == 413
        assert "5 MB" in resp.json()["detail"]


def test_any_file_type_is_accepted():
    """A prototype takes whatever the family actually produced -- a photo,
    a PDF scan, a screenshot. Restricting the type would refuse real
    documents to enforce a rule nobody asked for."""
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999")
        pid = _new_patient(client, {"Authorization": f"Bearer {asha['access_token']}"})
        _age_patient(pid, days=40)

        bmo = _login(client, "9999999902")
        resp = client.post(f"/api/v1/patients/{pid}/correction",
                           headers={"Authorization": f"Bearer {bmo['access_token']}"},
                           data={"age": 29, "reason": "Age corrected from the MCP card."},
                           files={"document": ("card.pdf", io.BytesIO(b"%PDF-1.4 scan"), "application/pdf")})
        assert resp.status_code == 200, resp.text


def test_an_asha_cannot_use_the_official_route_at_all():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        pid = _new_patient(client, headers)
        _age_patient(pid, days=40)

        resp = client.post(f"/api/v1/patients/{pid}/correction", headers=headers,
                           data={"name": "Meera Patil", "reason": "Trying the official route."},
                           files=_document())
        assert resp.status_code == 403


def test_the_correction_and_its_proof_stay_together():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999")
        pid = _new_patient(client, {"Authorization": f"Bearer {asha['access_token']}"})
        _age_patient(pid, days=40)

        bmo = _login(client, "9999999902")
        headers = {"Authorization": f"Bearer {bmo['access_token']}"}
        client.post(f"/api/v1/patients/{pid}/correction", headers=headers,
                    data={"name": "Meera Patil", "reason": "Aadhaar card produced."},
                    files=_document())

        listing = client.get(f"/api/v1/patients/{pid}/corrections", headers=headers)
        assert listing.status_code == 200
        entry = listing.json()["corrections"][0]
        assert entry["changed_fields"] == ["name"]
        assert entry["corrected_by"] == "Dr. Vikram Rao"
        assert entry["document_name"] == "aadhaar.jpg"

        # And the document itself comes back byte for byte.
        file_resp = client.get(
            f"/api/v1/patients/{pid}/corrections/{entry['document_id']}/file", headers=headers)
        assert file_resp.status_code == 200
        assert file_resp.content.startswith(b"\xff\xd8\xff")
