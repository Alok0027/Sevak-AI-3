"""Find (and optionally remove) test-suite debris in the demo database.

Until tests/conftest.py was given its own database, every `pytest` run
wrote its fixtures into sevakai_dev.db -- the file the demo and the
dashboard read. That is fixed going forward, but the rows already there
stay there, and they are what a judge sees: one ASHA holding hundreds of
pending follow-ups against a single patient, another holding dozens of
distinct patients all named "Outside Sub-Centre Patient".

Nothing here is clever. It only removes rows that could not plausibly be
real:

  * patients carrying a literal test name AND no recorded visit
  * the synthetic out-of-sub-centre worker, once her patients are gone
  * runaway pending follow-ups -- past --max-followups for one patient,
    the oldest are cancelled, never the newest

Reports by default. Pass --apply to actually write, and take a copy of
the database first; there is no undo.

    python scripts/audit_demo_data.py
    python scripts/audit_demo_data.py --apply
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from app.db.models.action import Action
from app.db.models.patient import Patient
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.db.session import SessionLocal

# Names only a fixture would ever produce. Deliberately exact matches --
# no fuzzy matching on a table of real patient records.
TEST_PATIENT_NAMES = {
    "Outside Sub-Centre Patient",
    "Asha Test",
    "Kamla Devi",
    "Test Patient",
}
TEST_WORKER_PHONES = {"9999990077", "9111111111"}

# The strongest signal available, and the one that actually caught the
# debris: a sub-centre id no district would ever issue. Everything under
# it -- the worker, her patients, their visits and actions -- came from a
# fixture, whether or not those patients have visits attached.
TEST_SUB_CENTRE_PREFIX = "SC-TEST-"

DEFAULT_MAX_FOLLOWUPS = 3


def audit(db, max_followups: int) -> dict:
    """Everything that looks like debris, with the evidence for each."""
    visit_counts: dict[str, int] = defaultdict(int)
    for (patient_id,) in db.query(Visit.patient_id).all():
        visit_counts[patient_id] += 1

    # Patient.name is an EncryptedString, so the stored column holds
    # ciphertext and a SQL `IN (...)` on plaintext matches nothing -- and
    # matches it silently, which reads as "nothing to clean". Load the
    # rows and compare after SQLAlchemy has decrypted them.
    test_workers = (
        db.query(Worker)
        .filter(
            (Worker.phone.in_(TEST_WORKER_PHONES))
            | (Worker.sub_centre_id.like(f"{TEST_SUB_CENTRE_PREFIX}%"))
        )
        .all()
    )
    test_worker_ids = {w.worker_id for w in test_workers}

    named = [p for p in db.query(Patient).all() if p.name in TEST_PATIENT_NAMES]
    # Two ways to be debris. A patient under a test sub-centre goes
    # regardless of visits -- the visits are fixtures too. A test-*named*
    # patient under a real worker only goes if nobody has recorded a real
    # visit against her since, because at that point she is somebody's
    # data whatever she is called.
    stale_patients = [
        p
        for p in named
        if p.worker_id in test_worker_ids or visit_counts.get(p.patient_id, 0) == 0
    ]
    stale_ids = {p.patient_id for p in stale_patients}
    stale_patients += [
        p
        for p in db.query(Patient).filter(Patient.worker_id.in_(test_worker_ids or {""})).all()
        if p.patient_id not in stale_ids
    ]
    stale_ids = {p.patient_id for p in stale_patients}
    kept_patients = [p for p in named if p.patient_id not in stale_ids]

    # Runaway follow-ups: group pending actions by patient via their visit.
    pending = (
        db.query(Action, Visit)
        .join(Visit, Action.visit_id == Visit.visit_id)
        .filter(Action.type == "followup", Action.status == "pending")
        .all()
    )
    by_patient: dict[str, list[Action]] = defaultdict(list)
    for action, visit in pending:
        by_patient[visit.patient_id].append(action)

    runaway = {}
    for patient_id, actions in by_patient.items():
        if len(actions) > max_followups:
            # Newest first; keep the head, cancel the tail.
            actions.sort(
                key=lambda a: (a.due_at is not None, a.due_at),
                reverse=True,
            )
            runaway[patient_id] = actions[max_followups:]

    return {
        "stale_patients": stale_patients,
        "kept_patients": kept_patients,
        "test_workers": test_workers,
        "runaway": runaway,
        "pending_total": len(pending),
    }


def describe(db, findings: dict, max_followups: int) -> None:
    stale = findings["stale_patients"]
    kept = findings["kept_patients"]
    workers = findings["test_workers"]
    runaway = findings["runaway"]
    excess = sum(len(v) for v in runaway.values())

    print(f"Fixture patients to remove              : {len(stale)}")
    for name in sorted({p.name for p in stale}):
        count = sum(1 for p in stale if p.name == name)
        print(f"    {count:>4} x {name}")
    if kept:
        print(f"Test-named patients WITH visits (kept)  : {len(kept)}")

    print(f"Synthetic test workers                  : {len(workers)}")
    for w in workers:
        print(f"    {w.name} ({w.phone}, {w.sub_centre_id})")

    print(f"Pending follow-ups in total             : {findings['pending_total']}")
    print(f"Patients over the {max_followups}-follow-up cap        : {len(runaway)}")
    if runaway:
        worst = sorted(runaway.items(), key=lambda kv: -len(kv[1]))[:5]
        for patient_id, actions in worst:
            patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
            name = patient.name if patient else patient_id[:8]
            print(f"    {name}: {len(actions) + max_followups} pending, would cancel {len(actions)}")
    print(f"Follow-up rows that would be cancelled   : {excess}")


def apply(db, findings: dict) -> None:
    stale = findings["stale_patients"]
    stale_ids = {p.patient_id for p in stale}

    # Visits first, then their actions, or the foreign keys dangle.
    if stale_ids:
        visit_ids = [
            v.visit_id for v in db.query(Visit).filter(Visit.patient_id.in_(stale_ids)).all()
        ]
        if visit_ids:
            db.query(Action).filter(Action.visit_id.in_(visit_ids)).delete(synchronize_session=False)
            db.query(Visit).filter(Visit.visit_id.in_(visit_ids)).delete(synchronize_session=False)
        db.query(Patient).filter(Patient.patient_id.in_(stale_ids)).delete(synchronize_session=False)

    for worker in findings["test_workers"]:
        remaining = db.query(Patient).filter(Patient.worker_id == worker.worker_id).count()
        if remaining == 0:
            db.query(Worker).filter(Worker.worker_id == worker.worker_id).delete(
                synchronize_session=False
            )

    # Cancelled, not deleted: a follow-up that was created is a fact, and
    # the completion chart counts both states. Deleting them would quietly
    # improve every compliance figure on the dashboard.
    for actions in findings["runaway"].values():
        for action in actions:
            action.status = "cancelled"

    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes (default: report only)")
    parser.add_argument(
        "--max-followups",
        type=int,
        default=DEFAULT_MAX_FOLLOWUPS,
        help=f"pending follow-ups to keep per patient (default {DEFAULT_MAX_FOLLOWUPS})",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        findings = audit(db, args.max_followups)
        describe(db, findings, args.max_followups)
        if args.apply:
            apply(db, findings)
            print("\nApplied.")
            after = audit(db, args.max_followups)
            print(f"Pending follow-ups now: {after['pending_total']}")
        else:
            print("\nReport only. Re-run with --apply to write (back the database up first).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
