"""Move the demo dataset forward in time so it looks like a live system.

A seeded database ages badly. The data was generated once, months ago,
and every date in it stayed where it was -- so the dashboard opens on
"Visits today: 0", the 14-day chart is flat at zero, and the follow-up
list is full of tasks ninety days past their deadline. None of that is a
bug. It is just a dataset that stopped, and it reads to anyone looking as
a system nobody uses.

Two passes:

1. Shift every timestamp forward by the same amount, so the newest visit
   lands on today. One offset for every table, so the relationships
   between rows -- a follow-up due 48 hours after its visit, an
   escalation fired two days later -- survive exactly as they were.

2. Close follow-ups that are still absurdly overdue. A real ASHA does not
   carry a task ninety days past its deadline; she either did it or the
   case moved on. Anything more than `--overdue-days` late is marked
   done, which leaves a believable tail of recently-late tasks instead of
   a wall of three-month-old ones.

    python -m scripts.refresh_demo_dates --dry-run     # show, change nothing
    python -m scripts.refresh_demo_dates               # apply

Safe to re-run: a second pass finds the newest visit already on today and
shifts by zero. Synthetic data only -- never point this at real records.
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func  # noqa: E402

from app.db.models.action import Action  # noqa: E402
from app.db.models.audit_log import AuditLog  # noqa: E402
from app.db.models.hmis_report import HmisReport  # noqa: E402
from app.db.models.patient import Patient  # noqa: E402
from app.db.models.risk_flag import RiskFlag  # noqa: E402
from app.db.models.visit import Visit  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402

# Every datetime column that carries demo history. Listed explicitly
# rather than discovered, so a column added later is a deliberate choice
# to shift rather than something that quietly moves.
SHIFTED = [
    (Visit, ["created_at", "synced_at"]),
    (RiskFlag, ["created_at", "escalated_at", "actioned_at"]),
    (Action, ["created_at", "due_at", "sent_at"]),
    (Patient, ["created_at"]),
    (AuditLog, ["timestamp"]),
    (HmisReport, ["generated_at"]),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overdue-days", type=int, default=30,
                        help="close follow-ups later than this many days (default 30)")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        newest = db.query(func.max(Visit.created_at)).scalar()
        if newest is None:
            print("No visits in this database.")
            return

        now = datetime.now(timezone.utc)
        if newest.tzinfo is None:
            newest = newest.replace(tzinfo=timezone.utc)
        shift = now - newest

        print(f"newest visit : {newest.date()}")
        print(f"today        : {now.date()}")
        print(f"shift        : {shift.days} days forward")

        cutoff = now - timedelta(days=args.overdue_days)
        stale = (
            db.query(Action)
            .filter(Action.type == "followup", Action.status == "pending",
                    Action.due_at.isnot(None), Action.due_at < cutoff - shift)
            .count()
        )
        print(f"follow-ups more than {args.overdue_days} days late : {stale}")

        if args.dry_run:
            print("\n--dry-run: nothing written.")
            return
        if shift.days <= 0 and stale == 0:
            print("\nNothing to do.")
            return

        moved = 0
        for model, columns in SHIFTED:
            for column in columns:
                col = getattr(model, column)
                moved += (
                    db.query(model)
                    .filter(col.isnot(None))
                    .update({col: col + shift}, synchronize_session=False)
                )
        db.commit()

        closed = (
            db.query(Action)
            .filter(Action.type == "followup", Action.status == "pending",
                    Action.due_at.isnot(None), Action.due_at < cutoff)
            .update({Action.status: "done"}, synchronize_session=False)
        )
        db.commit()

        print(f"\nShifted {moved} timestamps and closed {closed} long-overdue follow-ups.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
