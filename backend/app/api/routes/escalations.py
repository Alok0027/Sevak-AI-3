"""GET /api/v1/escalations/pending (FR-06.2)."""
from fastapi import APIRouter, Depends, Query

from app.agents.agent5_escalation import check_and_escalate, get_pending_escalations
from app.api.deps import DbSession, require_roles, visible_sub_centres

router = APIRouter(prefix="/api/v1/escalations", tags=["escalations"])


@router.get("/pending")
def pending_escalations(
    db: DbSession,
    # Not admin. This endpoint names patients -- her name, age, village and
    # the clinical reason she was flagged -- so it is patient record
    # access even though it arrives as a supervisor's worklist rather than
    # as a patient page. Closing /patients and /reports to admin while
    # leaving this open meant the block could be walked straight around
    # from the Overview screen. See app/api/routes/patients.py.
    user=Depends(require_roles("anm", "bmo")),
    bmo_id: str | None = Query(default=None),
) -> dict:
    # Run the 48h auto-escalation check inline so the list is always current
    # even without a separate scheduler running yet (swap for a real cron /
    # APScheduler job per the module docstring once deployed).
    check_and_escalate(db)
    scope = visible_sub_centres(user, db)
    return {"escalations": get_pending_escalations(db, sub_centre_id=scope)}
