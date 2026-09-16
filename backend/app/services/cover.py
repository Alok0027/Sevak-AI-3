"""Who is standing in for whom, today.

One function answers the only question the rest of the app asks:
`covered_worker_ids(db, worker_id)` -- whose patients may this ASHA see
right now, besides her own.

It lives here rather than inline in a route because three places need the
same answer and must not disagree: her patient list, the task board, and
the guard on recording a visit. A list that shows a covered patient while
the visit endpoint refuses her is worse than not having cover at all --
she walks to the house and then cannot record what she found.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.absence import WorkerAbsence


def _today() -> date:
    return datetime.now(timezone.utc).date()


def active_absences_for(db: Session, worker_id: str, on: date | None = None) -> list[WorkerAbsence]:
    """The absences this worker is currently *covering* for somebody else."""
    day = on or _today()
    return (
        db.query(WorkerAbsence)
        .filter(
            WorkerAbsence.covering_worker_id == worker_id,
            WorkerAbsence.starts_on <= day,
            WorkerAbsence.ends_on >= day,
            WorkerAbsence.ended_at.is_(None),
        )
        .all()
    )


def covered_worker_ids(db: Session, worker_id: str, on: date | None = None) -> list[str]:
    """Whose patients this worker may also see today. Usually empty."""
    return [a.worker_id for a in active_absences_for(db, worker_id, on)]


def my_active_absence(db: Session, worker_id: str, on: date | None = None) -> WorkerAbsence | None:
    """Her own leave, if she is away right now."""
    day = on or _today()
    return (
        db.query(WorkerAbsence)
        .filter(
            WorkerAbsence.worker_id == worker_id,
            WorkerAbsence.starts_on <= day,
            WorkerAbsence.ends_on >= day,
            WorkerAbsence.ended_at.is_(None),
        )
        .first()
    )


def upcoming_or_active_absence(db: Session, worker_id: str, on: date | None = None) -> WorkerAbsence | None:
    """Her leave, including one she has booked but not started.

    Used when she opens her profile: "you are away from Monday" is the
    thing she wants confirmed, and an endpoint that only reported leave
    already in progress would show her nothing until it was too late to
    change it.
    """
    day = on or _today()
    return (
        db.query(WorkerAbsence)
        .filter(
            WorkerAbsence.worker_id == worker_id,
            WorkerAbsence.ends_on >= day,
            WorkerAbsence.ended_at.is_(None),
        )
        .order_by(WorkerAbsence.starts_on.asc())
        .first()
    )


def visible_worker_ids(db: Session, worker_id: str, on: date | None = None) -> list[str]:
    """Her own id, plus anyone she is covering.

    The one thing a caller should use when scoping a query to "her work".
    """
    return [worker_id, *covered_worker_ids(db, worker_id, on)]
