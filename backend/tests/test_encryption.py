"""NFR-SC1: patient data encrypted at rest. Verifies both ends -- the raw
DB row is ciphertext, and the API still returns the real plaintext, since
the whole point of column-level encryption is that nothing above the model
layer should notice it's there."""
import sqlite3

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.encryption import _MARKER, decrypt_field, encrypt_field
from app.db.session import SessionLocal
from app.main import app
from scripts.seed_synthetic_data import seed_demo_fixtures


def _login(client: TestClient, phone: str, pin: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed():
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
    finally:
        db.close()


def test_round_trip_preserves_the_original_value():
    ciphertext = encrypt_field("Meera Patil")
    assert ciphertext.startswith(_MARKER)
    assert ciphertext != "Meera Patil"
    assert decrypt_field(ciphertext) == "Meera Patil"


def test_encrypting_the_same_value_twice_gives_different_ciphertext():
    # Random nonce per call -- this is also *why* Worker.phone (the login
    # lookup key) and Patient.village (heatmap grouping) are deliberately
    # left unencrypted: SQL equality can't match against either result.
    assert encrypt_field("Meera Patil") != encrypt_field("Meera Patil")


def test_none_passes_through_untouched():
    assert encrypt_field(None) is None
    assert decrypt_field(None) is None


def test_unmarked_value_is_treated_as_pre_migration_plaintext():
    # scripts/encrypt_existing_data.py relies on exactly this: a value
    # without the marker is a leftover plaintext row, not garbage to crash on.
    assert decrypt_field("Meera Patil") == "Meera Patil"


def test_patient_name_is_ciphertext_at_rest_but_plaintext_over_the_api():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}

        # The API sees the real name.
        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=headers)
        assert patients.status_code == 200, patients.text
        meera = next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")

        # The database row itself does not -- it's this session's own AES-256
        # ciphertext, not the plaintext name.
        #
        # Read through SQLAlchemy rather than sqlite3.connect(): this has
        # to hold on Postgres too, and hardcoding the SQLite driver meant
        # the one test that proves patient data is encrypted at rest was
        # the only test that could not run against the database we
        # actually deploy on. `text()` with a bound parameter, not the
        # ORM, so the column is read raw and never passes back through
        # the EncryptedString type that would decrypt it.
        from sqlalchemy import text

        from app.db.session import engine

        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT name FROM patients WHERE patient_id = :pid"),
                {"pid": meera["id"]},
            ).fetchone()
        assert row is not None
        assert row[0] != "Meera Patil"
        assert row[0].startswith(_MARKER)


def test_referral_letter_and_risk_drivers_are_ciphertext_at_rest():
    """The conclusion deserves the same protection as the recording.

    `visits.transcript` was encrypted while `actions.content` was not --
    so the audio's transcription was protected and the referral letter
    derived from it, which names the patient, her age, her pregnancy stage
    and the clinical reason she is being referred, sat in plaintext next to
    it. Same for `risk_flags.drivers_json`, which quotes her actual
    readings.
    """
    from sqlalchemy import text

    from app.db.models.action import Action
    from app.db.models.risk_flag import RiskFlag
    from app.db.models.visit import Visit
    from app.db.session import SessionLocal, engine

    db = SessionLocal()
    try:
        visit = Visit(patient_id="p-enc", worker_id="w-enc", risk_level="HIGH")
        db.add(visit)
        db.flush()
        letter = "REFERRAL LETTER\n\nPatient: Meera Patil, Age 28\nReason: BP 140/90"
        drivers = '[{"observation": "BP 140/90", "reason": "above threshold"}]'
        db.add(Action(visit_id=visit.visit_id, type="referral", content=letter))
        db.add(RiskFlag(visit_id=visit.visit_id, risk_level="HIGH",
                        drivers_json=drivers, override_reason="Cuff was faulty"))
        db.commit()

        # The ORM hands back exactly what went in.
        action = db.query(Action).filter(Action.visit_id == visit.visit_id).one()
        flag = db.query(RiskFlag).filter(RiskFlag.visit_id == visit.visit_id).one()
        assert action.content == letter
        assert flag.drivers_json == drivers
        assert flag.override_reason == "Cuff was faulty"

        # The rows themselves do not.
        with engine.connect() as conn:
            raw_action = conn.execute(
                text("SELECT content FROM actions WHERE visit_id = :v"),
                {"v": visit.visit_id},
            ).fetchone()
            raw_flag = conn.execute(
                text("SELECT drivers_json, override_reason FROM risk_flags WHERE visit_id = :v"),
                {"v": visit.visit_id},
            ).fetchone()

        assert "Meera Patil" not in raw_action[0]
        assert raw_action[0].startswith(_MARKER)
        assert "140/90" not in raw_flag[0]
        assert raw_flag[0].startswith(_MARKER)
        assert raw_flag[1].startswith(_MARKER)
    finally:
        db.rollback()
        db.close()
