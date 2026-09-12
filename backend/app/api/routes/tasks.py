"""GET /api/v1/tasks/{worker_id} (FR-07.3: pending follow-ups sorted by urgency)
and POST /api/v1/tasks/{action_id}/complete (mark one done from the app).

Not in the SRS's table 19 endpoint list, but FR-07.3 requires the mobile app
to show this and there's otherwise no way to fetch it -- added here rather
than leaving the requirement unimplementable. The complete endpoint is what
lets the ANM/BMO "done vs pending" follow-up chart reflect real completions
from the field rather than a count that only ever grows."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import DbSession, require_roles
from app.db.models.action import Action
from app.db.models.patient import Patient
from app.db.models.visit import Visit
from app.services import followup_schedule

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("/{worker_id}")
def list_tasks(
    worker_id: str,
    db: DbSession,
    _user=Depends(require_roles("asha")),
) -> dict:
    rows = (
        db.query(Action, Visit, Patient)
        .join(Visit, Action.visit_id == Visit.visit_id)
        .join(Patient, Visit.patient_id == Patient.patient_id)
        .filter(Visit.worker_id == worker_id, Action.type == "followup", Action.status == "pending")
        .all()
    )
    # FR-07.3: sorted HIGH (48h) -> MEDIUM (7d) -> LOW (30d), i.e. soonest due_at first.
    # Each task also carries how late it is, classified by the same rule the
    # supervisor's compliance view uses (app/services/followup_schedule.py),
    # so an ASHA is never shown "due today" for a visit her BMO is seeing
    # as overdue.
    now = datetime.now(timezone.utc)
    tasks = []
    for action, visit, patient in rows:
        bucket, hours_overdue = followup_schedule.classify(action.due_at, now)
        tasks.append(
            {
                "action_id": action.action_id,
                "patient_id": patient.patient_id,
                "patient_name": patient.name,
                "village": patient.village,
                "content": action.content,
                "risk_level": visit.risk_level,
                "due_at": action.due_at.isoformat() if action.due_at else None,
                "bucket": bucket,
                "hours_overdue": hours_overdue,
                "label": followup_schedule.describe(bucket, hours_overdue),
            }
        )
    tasks.sort(key=lambda t: t["due_at"] or "9999")
    # "Today" is everything she still owes by end of today -- an overdue
    # visit is more today's work than one due this afternoon, so the app's
    # today list is those two buckets together, not due_today alone.
    due_now = [t for t in tasks if t["bucket"] in (followup_schedule.OVERDUE, followup_schedule.DUE_TODAY)]
    # ...but collapsed to one row per *person*. An ASHA walks to a house,
    # not to an action row: a patient with six pending follow-ups is still
    # one door to knock on, and listing her six times pushes five other
    # women off the screen and makes the whole list read as a single
    # repeated name. She sees the most urgent reason to go, plus a count of
    # what else is waiting there so nothing is silently dropped; the full
    # per-action list is still in `tasks` for the detail screen.
    today = []
    seen: dict[str, dict] = {}
    for t in due_now:  # already sorted soonest-due first, so first seen is most urgent
        existing = seen.get(t["patient_id"])
        if existing is None:
            entry = dict(t, also_pending=0)
            seen[t["patient_id"]] = entry
            today.append(entry)
        else:
            existing["also_pending"] += 1
    return {
        "tasks": tasks,
        "today": today,
        "summary": {
            "overdue": sum(1 for t in tasks if t["bucket"] == followup_schedule.OVERDUE),
            "due_today": sum(1 for t in tasks if t["bucket"] == followup_schedule.DUE_TODAY),
            "upcoming": sum(1 for t in tasks if t["bucket"] == followup_schedule.UPCOMING),
        },
    }


@router.post("/{action_id}/complete")
def complete_task(
    action_id: str,
    db: DbSession,
    user=Depends(require_roles("asha")),
) -> dict:
    row = (
        db.query(Action, Visit)
        .join(Visit, Action.visit_id == Visit.visit_id)
        .filter(Action.action_id == action_id, Action.type == "followup")
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    action, visit = row
    if visit.worker_id != user.worker_id:
        raise HTTPException(status_code=403, detail="Not your task")
    action.status = "done"
    action.sent_at = datetime.now(timezone.utc)
    db.commit()
    return {"action_id": action_id, "status": "done"}
