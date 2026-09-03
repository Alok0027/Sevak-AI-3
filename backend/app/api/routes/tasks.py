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
    tasks = [
        {
            "action_id": action.action_id,
            "patient_id": patient.patient_id,
            "patient_name": patient.name,
            "content": action.content,
            "risk_level": visit.risk_level,
            "due_at": action.due_at.isoformat() if action.due_at else None,
        }
        for action, visit, patient in rows
    ]
    tasks.sort(key=lambda t: t["due_at"] or "9999")
    return {"tasks": tasks}


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
