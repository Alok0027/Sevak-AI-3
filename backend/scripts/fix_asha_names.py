"""One-off data fix: ASHA (Accredited Social Health Activist) is a
women-only community health worker role under India's National Health
Mission -- there is no such thing as a male ASHA worker. The synthetic seed
data generated ASHA names with Faker's generic name() before this was
caught, which produces a roughly even mix of male- and female-sounding
names -- so some seeded "ASHA workers" were unrealistic. (Their patients are
correctly a real mix of genders via Patient.gender -- that part was never
wrong and is untouched here.)

This renames every ASHA worker to a fresh female name, EXCEPT the fixed demo
account (Sunita Sharma) -- already a real female name, and referenced by
name in demo materials, so it's left alone rather than needlessly
re-rolled. worker_id/phone/sub_centre/patients/visits are all untouched;
only the `name` column changes, so nothing relational breaks.

Safe to run more than once (renaming an already-female-named worker again is
harmless, just gives her a different fresh name) -- not idempotent in the
sense of detecting "already fixed", because there's no reliable way to
detect a name's gender after the fact; it's idempotent in the sense that
running it twice doesn't corrupt anything, just costs an unnecessary rename.

Usage: python -m scripts.fix_asha_names
"""
from faker import Faker

from app.db.models.worker import Worker
from app.db.session import SessionLocal, init_db
from scripts.seed_synthetic_data import DEMO_WORKER_PHONE

fake = Faker("en_IN")


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        asha_workers = db.query(Worker).filter(Worker.role == "asha", Worker.phone != DEMO_WORKER_PHONE).all()
        if not asha_workers:
            print("No non-demo ASHA workers found -- nothing to fix.")
            return
        for w in asha_workers:
            w.name = fake.name_female()
        db.commit()
        print(f"Renamed {len(asha_workers)} ASHA workers to female names (demo account Sunita Sharma left as-is).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
