"""Every worker must belong somewhere, and the numbers must reconcile.

The failure this guards against is not a crash -- it is a dashboard that
looks fine and is wrong. An ASHA seeded into a sub-centre no ANM covers,
in a district no BMO owns, is invisible to the system rather than a
smaller part of it: her patients are missing from the district totals,
her HIGH-risk cases reach no supervisor, and the escalation queue is
quietly incomplete. On the deployed database this was 18 of 25 ASHAs,
112 patients and 496 visits -- and nothing anywhere said so.
"""
from app.db.models.patient import Patient
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.db.session import SessionLocal
from scripts.seed_synthetic_data import (
    DISTRICT_ID,
    SUB_CENTRES,
    ensure_supervisors,
    seed_random_workers,
)


def _newly_seeded(db, before: set[str]) -> list[Worker]:
    """Only the ASHAs this test created.

    The suite shares one database and several other tests commit workers
    into throwaway sub-centres (SC-TEST-*), so asserting over every ASHA
    in the table makes this file pass alone and fail in a full run -- and
    fail for something that is not the thing it is testing.
    """
    return [
        w for w in db.query(Worker).filter(Worker.role == "asha").all()
        if w.worker_id not in before
    ]


def test_every_seeded_asha_has_an_anm_above_her_and_a_bmo_above_that():
    db = SessionLocal()
    try:
        before = {w.worker_id for w in db.query(Worker).filter(Worker.role == "asha").all()}
        ensure_supervisors(db)
        seed_random_workers(db, n_workers=8, patients_per_worker=2, months_history=1)

        anm_sub_centres = {
            sc for (sc,) in db.query(Worker.sub_centre_id)
            .filter(Worker.role == "anm", Worker.sub_centre_id.isnot(None)).distinct()
        }
        assert anm_sub_centres, "no ANM exists at all"

        ashas = _newly_seeded(db, before)
        assert ashas, "the seeder created no ASHAs to check"
        orphans = [a for a in ashas if a.sub_centre_id not in anm_sub_centres]
        assert not orphans, (
            "these ASHAs have no ANM above them, so their patients reach nobody: "
            + ", ".join(f"{a.name} ({a.sub_centre_id})" for a in orphans[:5])
        )

        # And every sub-centre an ASHA is in must be one the seeder declares,
        # not a name invented per worker.
        unknown = {a.sub_centre_id for a in ashas} - set(SUB_CENTRES)
        assert not unknown, f"ASHAs in undeclared sub-centres: {sorted(unknown)}"
    finally:
        db.rollback()
        db.close()


def test_a_supervisor_sees_every_patient_in_her_scope():
    """What the ANM's scope contains and what her workers actually hold
    have to be the same set. A patient whose sub_centre_id disagrees with
    her worker's is counted in one roll-up and listed in another."""
    db = SessionLocal()
    try:
        ensure_supervisors(db)
        seed_random_workers(db, n_workers=6, patients_per_worker=2, months_history=1)

        for anm in db.query(Worker).filter(Worker.role == "anm").all():
            workers = db.query(Worker).filter(
                Worker.role == "asha", Worker.sub_centre_id == anm.sub_centre_id
            ).all()
            for w in workers:
                mismatched = (
                    db.query(Patient)
                    .filter(Patient.worker_id == w.worker_id,
                            Patient.sub_centre_id != w.sub_centre_id)
                    .count()
                )
                assert mismatched == 0, (
                    f"{w.name} holds {mismatched} patients filed to a different "
                    "sub-centre than she works in"
                )
    finally:
        db.rollback()
        db.close()


def test_every_visit_belongs_to_a_worker_who_belongs_to_a_sub_centre():
    """No visit may dangle: a visit whose worker has no sub-centre cannot
    be rolled up to any district figure."""
    db = SessionLocal()
    try:
        before = {w.worker_id for w in db.query(Worker).filter(Worker.role == "asha").all()}
        ensure_supervisors(db)
        seed_random_workers(db, n_workers=4, patients_per_worker=2, months_history=1)
        mine = {w.worker_id for w in _newly_seeded(db, before)}

        rows = (
            db.query(Visit, Worker)
            .join(Worker, Visit.worker_id == Worker.worker_id)
            .filter(Worker.worker_id.in_(mine))
            .all()
        )
        assert rows, "no visits were seeded to check"
        dangling = [v.visit_id for v, w in rows if not w.sub_centre_id or not w.district_id]
        assert not dangling, f"{len(dangling)} visits cannot be rolled up to a district"

        for _, w in rows:
            assert w.district_id == DISTRICT_ID
    finally:
        db.rollback()
        db.close()
