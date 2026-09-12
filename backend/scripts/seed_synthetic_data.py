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
from app.db.session import SessionLocal, init_db

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


def seed_random_workers(db, n_workers: int, patients_per_worker: int, months_history: int) -> None:
    # Put a handful of the random workers in the demo ANM's sub-centre
    # (SC-PUNE-01) so her roster/dashboard has more than the single demo
    # worker to show off sorting, filtering, and the leaderboard chart.
    demo_sub_centre_slots = min(6, n_workers)
    for i in range(n_workers):
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
                risk_level = random.choices(RISK_LEVELS, weights=RISK_WEIGHTS)[0]
                days_ago = random.randint(0, months_history * 30)
                created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
                visit = Visit(
                    patient_id=patient.patient_id,
                    worker_id=worker.worker_id,
                    transcript="[synthetic historical visit -- audio not retained]",
                    structured_json="{}",
                    risk_score=random.uniform(0.0, 1.0),
                    risk_level=risk_level,
                    created_at=created_at,
                    synced_at=created_at,
                )
                db.add(visit)
                db.flush()

                drivers = DRIVER_TEMPLATES.get(risk_level, [])
                db.add(
                    RiskFlag(
                        visit_id=visit.visit_id,
                        risk_level=risk_level,
                        drivers_json=json.dumps([{"observation": d[0], "reason": d[1]} for d in drivers]),
                        created_at=created_at,
                    )
                )

                # FR-04.3: every visit gets a follow-up task, due date by risk
                # level. Older ones are randomly resolved so the dashboard's
                # done/pending/overdue split has all three buckets populated.
                due_days = FOLLOWUP_DAYS[risk_level]
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
