"""Create the first admin account on a fresh deployment.

    cd backend
    BOOTSTRAP_ADMIN_NAME="Alok Kumar" \
    BOOTSTRAP_ADMIN_PHONE=9812345678 \
    BOOTSTRAP_ADMIN_PIN=4821 \
    PYTHONPATH=. python scripts/bootstrap_admin.py

Why this exists
---------------
Every account in SevakAI is created by an admin (SRS table 4: "Worker
onboarding" belongs to the Admin panel), or by a worker registering and an
admin approving. Both need an admin to already exist.

The only reason one ever did was SEED_DEMO_ON_START=true, which inserts the
demo cast -- Sunita, Dr. Rekha, Dr. Vikram, "Admin User" -- with the PIN
1234 printed in the repository. That is the right thing for a demo and
exactly the wrong thing for a real block office: turn the flag off, as the
render.yaml comment tells you to once real data exists, and nobody can sign
in at all, ever, with no way to fix it short of opening the database by
hand. Leave it on, and the district's admin account has a published PIN.

This is the way out of that: one admin, made deliberately, with a PIN
nobody else has seen.

Refuses to run if any admin already exists
------------------------------------------
Not a convenience check. A bootstrap script that can be run twice is a
back door: anyone who can reach the environment can mint themselves an
admin account on a live system and read every patient record in the
district. It has to be a thing that works exactly once.

Reads the PIN from the environment rather than a flag, so it does not end
up in shell history. Better still, pipe it: some hosts log the environment
of a one-off job.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import hash_pin  # noqa: E402
from app.db.models.worker import Worker  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.services.audit import record as audit_record  # noqa: E402

PIN_LENGTH = 4


def _fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    name = (os.environ.get("BOOTSTRAP_ADMIN_NAME") or "").strip()
    phone = "".join(ch for ch in (os.environ.get("BOOTSTRAP_ADMIN_PHONE") or "") if ch.isdigit())
    pin = (os.environ.get("BOOTSTRAP_ADMIN_PIN") or "").strip()

    if not name:
        _fail("BOOTSTRAP_ADMIN_NAME is not set")
    if len(phone) != 10:
        _fail("BOOTSTRAP_ADMIN_PHONE must be 10 digits")
    if not pin.isdigit() or len(pin) != PIN_LENGTH:
        _fail(f"BOOTSTRAP_ADMIN_PIN must be exactly {PIN_LENGTH} digits")
    # The PIN people reach for first, on the account that can read every
    # patient record in the district.
    if pin in {"1234", "0000", "1111"}:
        _fail("Pick a PIN that is not 1234, 0000 or 1111")

    init_db()
    db = SessionLocal()
    try:
        existing = db.query(Worker).filter(Worker.role == "admin").first()
        if existing is not None:
            _fail(
                "An admin account already exists "
                f"({existing.name}, {existing.phone}). Refusing to create another -- "
                "use the Admin panel, which records who created whom."
            )
        if db.query(Worker).filter(Worker.phone == phone).first() is not None:
            _fail(f"A worker already exists with phone {phone}")

        admin = Worker(
            name=name,
            phone=phone,
            pin_hash=hash_pin(pin),
            role="admin",
            status="active",
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

        # NFR-SC4. The one account nobody approved, so the trail has to say
        # where it came from -- an admin with no provenance is the first
        # thing an auditor asks about.
        audit_record(
            db,
            user_id=admin.worker_id,
            action_type="staff.bootstrap_admin",
            record_id=admin.worker_id,
            record_type="worker",
            details={"name": admin.name, "phone": admin.phone},
        )
        print(f"Created admin: {admin.name} ({admin.phone})")
        print("Sign in with that phone and the PIN you set, then create the rest from the panel.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
