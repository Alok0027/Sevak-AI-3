"""Computes real worker stats from the visits/actions tables -- backs the
roster and worker-history endpoints (dashboard drill-down, FR-08 'worker
performance metrics'). Nothing here is invented: every number is a count
or aggregate over rows the pipeline actually wrote."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models.action import Action
from app.db.models.patient import Patient
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.schemas.worker import WorkerStats


def list_worker_stats(
    db: Session,
    sub_centre_id: str | None = None,
    search: str | None = None,
    worker_id: str | None = None,
) -> list[WorkerStats]:
    query = db.query(Worker).filter(Worker.role == "asha")
    if sub_centre_id:
        query = query.filter(Worker.sub_centre_id == sub_centre_id)
    if search:
        query = query.filter(Worker.name.ilike(f"%{search}%"))
    if worker_id:
        query = query.filter(Worker.worker_id == worker_id)
    workers = query.all()

    if not workers:
        return []
    worker_ids = [w.worker_id for w in workers]

    patient_counts = dict(
        db.query(Patient.worker_id, func.count(func.distinct(Patient.patient_id)))
        .filter(Patient.worker_id.in_(worker_ids))
        .group_by(Patient.worker_id)
        .all()
    )
    visit_counts = dict(
        db.query(Visit.worker_id, func.count(Visit.visit_id))
        .filter(Visit.worker_id.in_(worker_ids))
        .group_by(Visit.worker_id)
        .all()
    )
    last_visit = dict(
        db.query(Visit.worker_id, func.max(Visit.created_at))
        .filter(Visit.worker_id.in_(worker_ids))
        .group_by(Visit.worker_id)
        .all()
    )
    risk_rows = (
        db.query(Visit.worker_id, Visit.risk_level, func.count(Visit.visit_id))
        .filter(Visit.worker_id.in_(worker_ids), Visit.risk_level.isnot(None))
        .group_by(Visit.worker_id, Visit.risk_level)
        .all()
    )
    risk_by_worker: dict[str, dict[str, int]] = {}
    for worker_id, level, count in risk_rows:
        risk_by_worker.setdefault(worker_id, {})[level] = count

    pending_rows = (
        db.query(Visit.worker_id, func.count(Action.action_id))
        .join(Action, Action.visit_id == Visit.visit_id)
        .filter(Visit.worker_id.in_(worker_ids), Action.type == "followup", Action.status == "pending")
        .group_by(Visit.worker_id)
        .all()
    )
    pending_by_worker = dict(pending_rows)

    stats = []
    for w in workers:
        risks = risk_by_worker.get(w.worker_id, {})
        stats.append(
            WorkerStats(
                worker_id=w.worker_id,
                worker_code=w.worker_code,
                name=w.name,
                phone=w.phone,
                sub_centre_id=w.sub_centre_id,
                language_pref=w.language_pref,
                total_patients=patient_counts.get(w.worker_id, 0),
                total_visits=visit_counts.get(w.worker_id, 0),
                high_risk_count=risks.get("HIGH", 0),
                medium_risk_count=risks.get("MEDIUM", 0),
                low_risk_count=risks.get("LOW", 0),
                pending_followups=pending_by_worker.get(w.worker_id, 0),
                last_visit_at=last_visit.get(w.worker_id),
            )
        )
    return stats


def get_worker_stats(db: Session, worker_id: str) -> WorkerStats | None:
    matches = list_worker_stats(db, worker_id=worker_id)
    return matches[0] if matches else None
