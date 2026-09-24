"""Two things in the demo data that read as generated rather than recorded.

1. Worker codes that name the wrong place. `repair_demo_data` moved 18
   ASHAs into Pune sub-centres but left their codes alone, so a worker
   page showed "ASHA-VILLE-20-001 · SC-PUNE-01" -- an identifier and a
   posting that contradict each other on the same line.

2. Every visit at the same second. The seeder stamped one base time and
   subtracted whole days from it, so all 705 visits landed at 00:32:35.
   A worker's timeline is a column of identical clock times, and 00:32 is
   not an hour anyone does home visits.

    python -m scripts.refresh_demo_realism --dry-run     # show, change nothing
    python -m scripts.refresh_demo_realism               # apply

Re-running is safe: codes already matching their sub-centre are left
alone, and a visit already inside working hours keeps its time.
"""
import argparse
import random
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models.action import Action  # noqa: E402
from app.db.models.risk_flag import RiskFlag  # noqa: E402
from app.db.models.visit import Visit  # noqa: E402
from app.db.models.worker import Worker  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.services import identity  # noqa: E402

# When an ASHA actually walks her ward. Home visits are a daytime job;
# nobody knocks on a pregnant woman's door at half past midnight.
FIRST_VISIT_HOUR = 8
LAST_VISIT_HOUR = 17


def _code_area(sub_centre_id: str | None) -> str:
    area = identity._slug(sub_centre_id)
    return area[3:] if area.startswith("SC-") else area


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--seed", type=int, default=20260924,
                        help="fixed by default, so a re-run reproduces the same times")
    args = parser.parse_args()
    rng = random.Random(args.seed)

    init_db()
    db = SessionLocal()
    try:
        # ── 1. Worker codes ──────────────────────────────────────────
        workers = db.query(Worker).order_by(Worker.created_at).all()
        stale = [
            w for w in workers
            if w.worker_code and w.sub_centre_id
            and _code_area(w.sub_centre_id) not in w.worker_code
        ]

        # ── 2. Visit times ───────────────────────────────────────────
        visits = db.query(Visit).all()
        off_hours = [
            v for v in visits
            if v.created_at and not (FIRST_VISIT_HOUR <= v.created_at.hour < LAST_VISIT_HOUR)
        ]

        print(f"worker codes naming the wrong sub-centre : {len(stale)}")
        print(f"visits outside {FIRST_VISIT_HOUR}:00-{LAST_VISIT_HOUR}:00       : {len(off_hours)} of {len(visits)}")
        if stale:
            print("\n  e.g. " + ", ".join(
                f"{w.name} {w.worker_code} in {w.sub_centre_id}" for w in stale[:3]))

        if args.dry_run:
            print("\n--dry-run: nothing written.")
            return
        if not stale and not off_hours:
            print("\nNothing to do.")
            return

        # Renumber per (role, sub-centre), matching identity.worker_code's
        # own rule: the serial is that person's position in their own
        # sub-centre, which is a fact somebody could check against a
        # register -- not a global insertion counter.
        serials: dict[tuple[str, str], int] = defaultdict(int)
        for w in workers:
            if not w.sub_centre_id:
                continue
            key = (w.role, w.sub_centre_id)
            serials[key] += 1
            if w in stale:
                w.worker_code = identity.worker_code(w.role, w.sub_centre_id, serials[key])

        # Move each visit within its own day, and carry everything hanging
        # off it by the identical delta. A follow-up due exactly 48 hours
        # after a HIGH visit has to stay exactly 48 hours after it.
        moved = 0
        for v in off_hours:
            old = v.created_at
            new = old.replace(
                hour=rng.randint(FIRST_VISIT_HOUR, LAST_VISIT_HOUR - 1),
                minute=rng.randint(0, 59),
                second=rng.randint(0, 59),
            )
            delta = new - old
            v.created_at = new
            if v.synced_at:
                v.synced_at = v.synced_at + delta
            for flag in db.query(RiskFlag).filter(RiskFlag.visit_id == v.visit_id).all():
                for field in ("created_at", "escalated_at", "actioned_at"):
                    value = getattr(flag, field)
                    if value:
                        setattr(flag, field, value + delta)
            for action in db.query(Action).filter(Action.visit_id == v.visit_id).all():
                for field in ("created_at", "due_at", "sent_at"):
                    value = getattr(action, field)
                    if value:
                        setattr(action, field, value + delta)
            moved += 1

        db.commit()
        print(f"\nRenumbered {len(stale)} worker codes and moved {moved} visits into working hours.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
