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
