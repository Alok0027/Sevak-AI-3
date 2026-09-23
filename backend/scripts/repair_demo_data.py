"""Repair synthetic demo rows that an older seeder wrote.

Two problems, both of which a code change alone cannot fix, because the
rows were already in the database before the fix shipped:

1. Every seeded visit carried the transcript
   "[synthetic historical visit -- audio not retained]". The patient
   timeline renders a transcript as a quotation, so that bracketed note
   appeared in quote marks on every visit of every patient, as though the
   ASHA had said it aloud.

2. Gender, name and pregnancy were drawn independently, producing rows
   like "Mohammed Bose, 39, Male, 2 months pregnant". A reviewer who sees
   the system assert a pregnant man stops believing its risk scores.

Both are repaired in place. Nothing is deleted: the visits, their
readings, their risk flags and every report built from them stay exactly
as they are, because those are the parts that are real.

    python -m scripts.repair_demo_data --dry-run     # show, change nothing
    python -m scripts.repair_demo_data               # apply

Safe to re-run; a second pass finds nothing to do. Against a deployed
database, pass the connection string in the environment:

    DATABASE_URL="postgres://..." python -m scripts.repair_demo_data
"""
import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faker import Faker  # noqa: E402

from app.db.models.patient import Patient  # noqa: E402
from app.db.models.visit import Visit  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402

fake = Faker("en_IN")

# What the old seeder wrote. Matched exactly rather than by pattern: a
# real transcript that merely mentions the word "synthetic" must survive.
PLACEHOLDER = "[synthetic historical visit -- audio not retained]"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change, write nothing")
    args = parser.parse_args()

    # Same bootstrap the app runs on boot. A database written before the
    # newest columns existed is missing them, and every ORM query names
    # every column -- so without this the script dies on `no such column:
    # patients.status` rather than repairing anything.
    init_db()

    db = SessionLocal()
    try:
        # Read through the ORM, not raw SQL: `transcript` is an encrypted
        # column, so the comparison has to happen after decryption. Rows
        # written before encryption shipped are plaintext and pass through
        # untouched -- either way the ORM hands back the real string.
        visits = [v for v in db.query(Visit).all() if v.transcript == PLACEHOLDER]

        pregnant_not_female = (
            db.query(Patient)
            .filter(Patient.pregnancy_stage.isnot(None), Patient.gender != "female")
            .all()
        )

        print(f"visits carrying the placeholder transcript : {len(visits)}")
        print(f"patients recorded pregnant but not female  : {len(pregnant_not_female)}")

        if pregnant_not_female:
            print("\n  e.g. " + ", ".join(
                f"{p.name} ({p.age}, {p.gender}, {p.pregnancy_stage})"
                for p in pregnant_not_female[:3]
            ))

        if args.dry_run:
            print("\n--dry-run: nothing written.")
            return

        if not visits and not pregnant_not_female:
            print("\nNothing to repair.")
            return

        for v in visits:
            # None, not a better placeholder. A visit with no audio has no
            # words to quote, and the timeline shows its readings instead.
            v.transcript = None

        for p in pregnant_not_female:
            # The name is regenerated alongside the gender on purpose:
            # leaving a male name on a record now marked female trades one
            # incoherent row for another. These are Faker-generated names
            # with no real person behind them, so coherence is worth more
            # than keeping the string stable.
            p.gender = "female"
            p.name = fake.name_female()
            if not (18 <= (p.age or 0) <= 45):
                p.age = random.randint(20, 40)

        db.commit()
        print(f"\nRepaired {len(visits)} transcripts and {len(pregnant_not_female)} patient records.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
