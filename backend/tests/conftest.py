"""
Test-suite-wide setup.

Two jobs, both of which must happen before any test module imports the
app, so pydantic-settings picks these up ahead of get_settings()'s first
call and its own .env read.

1. Force safe, network-free settings regardless of whatever the
   developer's local .env has (e.g. STT_PROVIDER=whisper for a live demo
   would otherwise make every test run download Whisper model weights).

2. Point the suite at its own throwaway database.

The second one is not housekeeping. Without it the suite ran against
sevakai_dev.db -- the same file the demo and the dashboard read -- so
every `pytest` invocation permanently added its fixtures to the data a
BMO sees. Repeated runs had left one seeded ASHA holding 228 pending
follow-ups against a single patient, and another holding 49 distinct
patients all named "Outside Sub-Centre Patient", which made the
visit-accountability table look broken when it was faithfully reporting
what was in the database. Tests write test data; they must not write it
where a demo will read it.
"""
import os
from pathlib import Path

os.environ["STT_PROVIDER"] = "mock"
os.environ["USE_MOCKS"] = "true"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["SMS_PROVIDER"] = "mock"

# Absolute, so it lands next to this file no matter which directory
# pytest was invoked from.
TEST_DB = Path(__file__).resolve().parent / "sevakai_test.db"

# SEVAKAI_TEST_DATABASE_URL, not DATABASE_URL: pointing the suite at a
# database is a thing you must ask for by a name that cannot be set by
# accident. DATABASE_URL is already in every .env and on every deploy
# platform, and honouring it here would mean a stray `pytest` wiping
# production.
#
# The reason to want this at all is that SQLite hides deployment bugs --
# it is permissive about types, DDL and concurrency in ways Postgres is
# not, so a suite that only ever runs on SQLite cannot tell you whether
# the app will survive a real deployment:
#
#   createdb sevakai_test
#   SEVAKAI_TEST_DATABASE_URL=postgresql+psycopg2://user:pw@localhost/sevakai_test pytest
_OVERRIDE = os.environ.get("SEVAKAI_TEST_DATABASE_URL")
os.environ["DATABASE_URL"] = _OVERRIDE or f"sqlite:///{TEST_DB}"

import pytest  # noqa: E402  (must come after the env vars above)


@pytest.fixture(scope="session", autouse=True)
def _fresh_test_database():
    """One clean database per run, seeded with the demo accounts.

    Recreated from empty each session so a test can never pass only
    because an earlier run left a row behind -- the failure mode that
    kept the duplicate-patient bug in the compliance view invisible.
    """
    from app.db.session import Base, SessionLocal, engine, init_db
    from scripts.seed_synthetic_data import seed_demo_fixtures

    if _OVERRIDE:
        # A real database cannot just be deleted from disk, so drop and
        # recreate the schema instead. Same guarantee: every run starts
        # from empty.
        Base.metadata.drop_all(bind=engine)
    elif TEST_DB.exists():
        TEST_DB.unlink()

    init_db()
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
    finally:
        db.close()

    yield

    # Left on disk deliberately: when a test fails, being able to open
    # the database it failed against is worth more than a tidy tree.
    # The next run starts by deleting it.
