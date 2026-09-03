"""Agent 5 -- Escalation (FR-06). Unlike Agents 1-4, this isn't a node in the
synchronous per-visit graph -- it's a periodic monitor (SRS: "Cron scheduler
+ Alert service"). Wire `check_and_escalate` to a scheduler (APScheduler,
Celery beat, or a simple cron hitting a maintenance endpoint) at your
deployment's chosen interval; call it directly in tests / the demo script
to simulate time passing without waiting 48 real hours.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models.patient import Patient
from app.db.models.risk_flag import RiskFlag
from app.db.models.visit import Visit
from app.db.models.worker import Worker

ESCALATION_THRESHOLD_HOURS = 48


def check_and_escalate(db: Session) -> list[str]:
    """FR-06.1: fire escalation for any HIGH risk flag with no recorded
    follow-up action after the 48-hour threshold. Returns escalated flag_ids."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ESCALATION_THRESHOLD_HOURS)
    candidates = (
        db.query(RiskFlag)
        .filter(
            RiskFlag.risk_level == "HIGH",
            RiskFlag.actioned_at.is_(None),
            RiskFlag.escalated_at.is_(None),
            RiskFlag.created_at <= cutoff,
        )
        .all()
    )
    escalated = []
    for flag in candidates:
        flag.escalated_at = datetime.now(timezone.utc)
        escalated.append(flag.flag_id)
    if escalated:
        db.commit()
    return escalated


def get_pending_escalations(db: Session, sub_centre_id: str | None = None) -> list[dict]:
    """FR-06.2: BMO/ANM dashboard feed -- all unactioned HIGH risk cases
    sorted by time elapsed since flag, regardless of whether the 48h
    auto-escalation has fired yet (so a supervisor sees it coming, not just
    after the threshold). `sub_centre_id` scopes an ANM to their own
    sub-centre (SRS table 4); leave None for BMO/Admin's district-wide view.
    Enriched with patient/worker context so the dashboard doesn't have to
    show a bare name with no way to judge severity."""
    import json

    now = datetime.now(timezone.utc)
    query = (
        db.query(RiskFlag, Visit, Patient, Worker)
        .join(Visit, RiskFlag.visit_id == Visit.visit_id)
        .join(Patient, Visit.patient_id == Patient.patient_id)
        .join(Worker, Visit.worker_id == Worker.worker_id)
        .filter(RiskFlag.risk_level == "HIGH", RiskFlag.actioned_at.is_(None))
    )
    if sub_centre_id:
        query = query.filter(Worker.sub_centre_id == sub_centre_id)

    results = []
    for flag, visit, patient, worker in query.all():
        created = flag.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        hours_elapsed = (now - created).total_seconds() / 3600
        drivers = []
        if flag.drivers_json:
            try:
                drivers = [d.get("reason", "") for d in json.loads(flag.drivers_json)]
            except (ValueError, AttributeError):
                drivers = []
        results.append(
            {
                "patient": patient.name,
                "patient_id": patient.patient_id,
                "patient_age": patient.age,
                "patient_village": patient.village,
                "flag_time": flag.created_at.isoformat(),
                "hours_elapsed": round(hours_elapsed, 1),
                "worker": worker.name,
                "worker_id": worker.worker_id,
                "worker_sub_centre": worker.sub_centre_id,
                "visit_id": visit.visit_id,
                "drivers": drivers,
            }
        )
    results.sort(key=lambda r: r["hours_elapsed"], reverse=True)
    return results
