"""
Synthetic demo dataset generator (SRS 12.2 / FR section 8 Week 4): zero real
patient data, ever -- everything here is Faker-generated or hardcoded demo
fixtures.

Usage:
    python -m scripts.seed_synthetic_data                  # small dev dataset
    python -m scripts.seed_synthetic_data --full            # SRS-spec 500/5000

Always creates one fixed, memorable demo account + patient matching the SRS
section 9 demo script exactly (Sunita Sharma / Meera Patil), so `python -m
scripts.demo_pipeline` and manual API testing have a known-good record to
use regardless of how many random ones were also generated.
"""
import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faker import Faker

from app.core.security import hash_pin
from app.db.models.action import Action
from app.db.models.patient import Patient
from app.db.models.risk_flag import RiskFlag
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.agents.agent2_risk_classification import classify
from app.agents.agent3_action_generation import FOLLOWUP_DAYS as AGENT3_FOLLOWUP_DAYS
from app.db.session import SessionLocal, init_db
from app.schemas.visit import ExtractedFields

fake = Faker("en_IN")

LANGUAGES = ["hi", "mr", "ta", "te", "bn"]
VILLAGES = [
    "Pune Rural", "Wagholi", "Shirur", "Baramati", "Daund", "Indapur",
    "Junnar", "Khed", "Ambegaon", "Purandar", "Velhe", "Mulshi",
]
RISK_LEVELS = ["HIGH", "MEDIUM", "LOW"]
RISK_WEIGHTS = [0.15, 0.30, 0.55]

# FR-04.3 follow-up windows and plausible NHM-style drivers per risk level,
# so seeded RiskFlags/escalations have real-looking (if synthetic) reasons
# instead of an empty list.
FOLLOWUP_DAYS = {"HIGH": 2, "MEDIUM": 7, "LOW": 30}
DRIVER_TEMPLATES = {
    "HIGH": [
        ("BP elevated", "BP at or above 140/90 meets NHM pre-eclampsia risk threshold."),
        ("Medication non-compliance", "Missed iron/medication course increases complication risk."),
    ],
    "MEDIUM": [
        ("BP slightly elevated", "BP above normal range; NHM protocol recommends closer monitoring."),
    ],
    "LOW": [],
}

DEMO_WORKER_PHONE = "9999999999"
DEMO_WORKER_PIN = "1234"


def seed_demo_fixtures(db) -> None:
    """The exact accounts/patient used in the SRS section 9 demo script."""
    if db.query(Worker).filter(Worker.phone == DEMO_WORKER_PHONE).first():
        return  # already seeded

    sunita = Worker(
        name="Sunita Sharma",
        phone=DEMO_WORKER_PHONE,
        pin_hash=hash_pin(DEMO_WORKER_PIN),
        language_pref="hi",
        sub_centre_id="SC-PUNE-01",
        role="asha",
    )
    anm = Worker(
        name="Dr. Rekha Joshi", phone="9999999901", pin_hash=hash_pin("1234"),
        role="anm", sub_centre_id="SC-PUNE-01",
    )
    bmo = Worker(
        name="Dr. Vikram Rao", phone="9999999902", pin_hash=hash_pin("1234"), role="bmo",
    )
    admin = Worker(
        name="Admin User", phone="9999999903", pin_hash=hash_pin("1234"), role="admin",
    )
    db.add_all([sunita, anm, bmo, admin])
    db.flush()

    meera = Patient(
        worker_id=sunita.worker_id,
        name="Meera Patil",
        age=28,
        gender="female",
        village="Pune Rural",
        phone="9876543210",
        pregnancy_stage="7 months",
    )
    db.add(meera)
    db.commit()

    print(f"Demo login -> phone: {DEMO_WORKER_PHONE}  pin: {DEMO_WORKER_PIN}  (role: asha)")
    print(f"Demo patient -> {meera.name} (patient_id: {meera.patient_id})")


# Where a real maternal-vitals distribution can be read from, if you have
# downloaded one. Optional on purpose: the seeder works without it, and
# nothing in the demo depends on the file being present.
#
#   https://archive.ics.uci.edu/dataset/863/maternal+health+risk
#   save Maternal Health Risk Data Set.csv as backend/data/maternal_vitals.csv
#
# Worth adding because real blood pressure and blood sugar co-vary, and two
# independent random draws do not -- you get a woman at 170/110 with
# textbook-normal glucose more often than pregnancy does.
VITALS_CSV = Path(__file__).resolve().parent.parent / "data" / "maternal_vitals.csv"

# Rough clinical bands used when the CSV is absent. Deliberately not one
# band per risk level: the point of this rewrite is that the risk level is
# *computed* from the vitals, so what is chosen here is how well the woman
# is, and the classifier decides what that means.
_PROFILES = [
    ("well",       0.55),
    ("borderline", 0.30),
    ("unwell",     0.15),
]


def _load_vitals_rows() -> list[dict]:
    """Read the UCI maternal-vitals CSV if it is there, converting units.

    The dataset records blood sugar in mmol/L and body temperature in
    Fahrenheit; this project uses mg/dL and Celsius throughout. Loading it
    raw would put every glucose reading around 7 -- far below the 126
    mg/dL threshold -- and every temperature near 98, which reads as a
    fatal fever. Converting here rather than at every use site means a
    future caller cannot forget.
    """
    if not VITALS_CSV.exists():
        return []
    import csv

    rows: list[dict] = []
    with VITALS_CSV.open(newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            try:
                rows.append({
                    "bp_systolic": int(float(raw["SystolicBP"])),
                    "bp_diastolic": int(float(raw["DiastolicBP"])),
                    # mmol/L -> mg/dL
                    "blood_sugar_random": int(round(float(raw["BS"]) * 18.0182)),
                    # Fahrenheit -> Celsius
                    "temperature_c": round((float(raw["BodyTemp"]) - 32) * 5 / 9, 1),
                })
            except (KeyError, ValueError, TypeError):
                continue  # one malformed row must not cost the whole file
    return rows


_VITALS_ROWS: list[dict] | None = None


def _synthetic_vitals() -> dict:
    """Plausible vitals for one visit, when no CSV is available."""
    profile = random.choices([p for p, _ in _PROFILES], weights=[w for _, w in _PROFILES])[0]
    if profile == "well":
        return {
            "bp_systolic": random.randint(100, 125),
            "bp_diastolic": random.randint(65, 82),
            "blood_sugar_random": random.randint(80, 130),
            "temperature_c": round(random.uniform(36.4, 37.2), 1),
        }
    if profile == "borderline":
        return {
            "bp_systolic": random.randint(126, 139),
            "bp_diastolic": random.randint(83, 89),
            "blood_sugar_random": random.randint(140, 195),
            "temperature_c": round(random.uniform(37.0, 37.8), 1),
        }
    return {
        "bp_systolic": random.randint(140, 175),
        "bp_diastolic": random.randint(90, 115),
        "blood_sugar_random": random.randint(200, 280),
        "temperature_c": round(random.uniform(37.5, 39.0), 1),
    }


def make_visit_vitals() -> dict:
    """One visit's readings -- from the real dataset when present."""
    global _VITALS_ROWS
    if _VITALS_ROWS is None:
        _VITALS_ROWS = _load_vitals_rows()
    if _VITALS_ROWS:
        return dict(random.choice(_VITALS_ROWS))
    return _synthetic_vitals()


def seed_random_workers(db, n_workers: int, patients_per_worker: int, months_history: int) -> None:
    # Put a handful of the random workers in the demo ANM's sub-centre
    # (SC-PUNE-01) so her roster/dashboard has more than the single demo
    # worker to show off sorting, filtering, and the leaderboard chart.
    demo_sub_centre_slots = min(6, n_workers)

    # Progress, because this used to print nothing at all until it was
    # completely finished. A thirty-second run and a hung one looked
    # identical from the outside, so the honest response to either was to
    # interrupt it -- which leaves a half-seeded database, because the
    # commit below is per worker. Three interrupted runs is how you end up
    # with 77 workers when you asked for 20.
    print(f"Seeding {n_workers} workers x {patients_per_worker} patients, "
          f"{months_history} months of history...", flush=True)

    for i in range(n_workers):
        print(f"  worker {i + 1}/{n_workers}", end="\r", flush=True)
        sub_centre_id = (
            "SC-PUNE-01" if i < demo_sub_centre_slots else f"SC-{fake.city_suffix().upper()}-{random.randint(1, 20):02d}"
        )
        worker = Worker(
            # ASHA (Accredited Social Health Activist) is a women-only role
            # under India's National Health Mission -- name_female(), not
            # name(), so a synthetic ASHA never comes out male. Her patients
            # (below) are still generated with a mixed name() + a genuine
            # random gender field, since patients of either sex are real.
            name=fake.name_female(),
            phone=fake.unique.numerify("9#########"),
            pin_hash=hash_pin("0000"),
            language_pref=random.choice(LANGUAGES),
            sub_centre_id=sub_centre_id,
            role="asha",
        )
        db.add(worker)
        db.flush()

        for _ in range(patients_per_worker):
            is_pregnant = random.random() < 0.35
            patient = Patient(
                worker_id=worker.worker_id,
                name=fake.name(),
                age=random.randint(18, 45) if is_pregnant else random.randint(1, 70),
                gender=random.choice(["female", "male"]),
                village=random.choice(VILLAGES),
                phone=fake.numerify("9#########"),
                pregnancy_stage=f"{random.randint(1, 9)} months" if is_pregnant else None,
            )
            db.add(patient)
            db.flush()

            n_visits = random.randint(0, 3 * months_history)
            for _ in range(n_visits):
                # Risk is computed, not chosen. Every historical visit runs
                # through the same classifier a live one does, over vitals
                # that are actually stored on the visit.
                #
                # It used to be `random.choices(RISK_LEVELS, weights=...)`
                # with structured_json="{}" and an unrelated random
                # risk_score -- so a HIGH patient had no readings, no
                # drivers that referred to anything, and a score that could
                # contradict her own label. The dashboard's risk
                # distribution was a weight somebody picked rather than an
                # output of the system, and clicking into a flagged patient
                # showed nothing behind the flag.
                vitals = make_visit_vitals()
                extracted = ExtractedFields(
                    pregnancy_stage=patient.pregnancy_stage,
                    medication_compliance=random.choices(
                        ["compliant", "non_compliant"], weights=[0.8, 0.2]
                    )[0],
                    **vitals,
                )
                result = classify(extracted)
                risk_level = result.risk_level

                days_ago = random.randint(0, months_history * 30)
                created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
                visit = Visit(
                    patient_id=patient.patient_id,
                    worker_id=worker.worker_id,
                    transcript="[synthetic historical visit -- audio not retained]",
                    structured_json=extracted.model_dump_json(),
                    risk_score=result.risk_score,
                    risk_level=risk_level,
                    created_at=created_at,
                    synced_at=created_at,
                )
                db.add(visit)
                db.flush()

                db.add(
                    RiskFlag(
                        visit_id=visit.visit_id,
                        risk_level=risk_level,
                        drivers_json=json.dumps([d.model_dump() for d in result.drivers]),
                        created_at=created_at,
                    )
                )

                # FR-04.3: every visit gets a follow-up task, due date by risk
                # level. Older ones are randomly resolved so the dashboard's
                # done/pending/overdue split has all three buckets populated.
                due_days = AGENT3_FOLLOWUP_DAYS.get(risk_level, 30)
                due_at = created_at + timedelta(days=due_days)
                is_resolved = random.random() < (0.75 if days_ago > due_days else 0.2)
                db.add(
                    Action(
                        visit_id=visit.visit_id,
                        type="followup",
                        content=f"Follow-up visit for {patient.name} ({risk_level} risk)",
                        status="done" if is_resolved else "pending",
                        due_at=due_at,
                        created_at=created_at,
                    )
                )
        db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="Generate SRS-spec 500 workers / 5000 patients")
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--patients-per-worker", type=int, default=None)
    parser.add_argument("--months", type=int, default=3, help="Months of visit history (SRS default: 3)")
    args = parser.parse_args()

    if args.full:
        n_workers, patients_per_worker = 500, 10  # 500 * 10 = 5,000 patients
    else:
        n_workers = args.workers or 20
        patients_per_worker = args.patients_per_worker or 8

    init_db()
    db = SessionLocal()
    try:
        # Say what is already there before adding to it. The seeder appends
        # rather than replaces, so running it twice doubles the district --
        # worth seeing before it happens rather than after.
        existing = db.query(Worker).count()
        if existing:
            print(f"NOTE: {existing} workers already in this database; "
                  f"seeding ADDS to them. Delete the .db file first for a clean set.",
                  flush=True)
        seed_demo_fixtures(db)
        seed_random_workers(db, n_workers=n_workers, patients_per_worker=patients_per_worker, months_history=args.months)
        total_workers = db.query(Worker).count()
        total_patients = db.query(Patient).count()
        total_visits = db.query(Visit).count()
        print(f"Seeded: {total_workers} workers, {total_patients} patients, {total_visits} historical visits.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
