"""GET /api/v1/escalations/pending (FR-06.2)."""
from fastapi import APIRouter, Depends, Query

from app.agents.agent5_escalation import check_and_escalate, get_pending_escalations
from app.api.deps import DbSession, require_roles, visible_sub_centres

router = APIRouter(prefix="/api/v1/escalations", tags=["escalations"])


@router.get("/pending")
def pending_escalations(
    db: DbSession,
    user=Depends(require_roles("anm", "bmo", "admin")),
    bmo_id: str | None = Query(default=None),
) -> dict:
    # Run the 48h auto-escalation check inline so the list is always current
    # even without a separate scheduler running yet (swap for a real cron /
    # APScheduler job per the module docstring once deployed).
    check_and_escalate(db)
    scope = visible_sub_centres(user, db)
    return {"escalations": get_pending_escalations(db, sub_centre_id=scope)}
