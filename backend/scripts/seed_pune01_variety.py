"""One-off top-up: adds a handful of additional ASHA workers (with their own
patients and visit history) into SC-PUNE-01 specifically -- the demo ANM's
own sub-centre.

Why this exists: seed_synthetic_data.py's seed_random_workers() already puts
up to 6 random workers into SC-PUNE-01 by design (see its own comment), so
the demo ANM's roster/dashboard has more than just the one demo ASHA to show
off sorting, filtering, drill-downs, etc. But that only happens if/when the
*random* part of the seeder is actually run with enough workers requested --
on a database that was only ever seeded via seed_demo_fixtures() (e.g. by
running the app or the test suite, which call it directly), SC-PUNE-01 ends
up with just Sunita Sharma, and the ANM's whole world is one ASHA and
whichever single patient she's been tested against most. Every list she
looks at -- her worker roster, the escalation queue -- ends up repeating the
same one or two names, which reads as "these lists are all the same" even
though they're not literally bugged.

This script tops that up without touching the fixed demo fixtures (Sunita
Sharma / Meera Patil / the ANM/BMO/Admin accounts) or any other sub-centre's
data. Idempotent-ish: skips if SC-PUNE-01 already has a healthy number of
ASHA workers, so running it twice by accident doesn't keep piling on more.

Usage: python -m scripts.seed_pune01_variety
"""
from app.db.models.worker import Worker
from app.db.session import SessionLocal, init_db
from scripts.seed_synthetic_data import seed_demo_fixtures, seed_random_workers

TARGET_SUB_CENTRE = "SC-PUNE-01"
MIN_ASHA_WORKERS = 5  # skip if SC-PUNE-01 already has at least this many


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)  # no-op if already seeded -- just guarantees Sunita/Meera exist first

        existing = db.query(Worker).filter(
            Worker.sub_centre_id == TARGET_SUB_CENTRE, Worker.role == "asha"
        ).count()
        if existing >= MIN_ASHA_WORKERS:
            print(f"{TARGET_SUB_CENTRE} already has {existing} ASHA workers -- nothing to do.")
            return

        # n_workers == the number seed_random_workers will route into
        # SC-PUNE-01 (its own demo_sub_centre_slots = min(6, n_workers)),
        # so asking for exactly 6 puts all 6 there, none elsewhere.
        seed_random_workers(db, n_workers=6, patients_per_worker=4, months_history=2)

        total = db.query(Worker).filter(
            Worker.sub_centre_id == TARGET_SUB_CENTRE, Worker.role == "asha"
        ).count()
        print(f"{TARGET_SUB_CENTRE} now has {total} ASHA workers.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
