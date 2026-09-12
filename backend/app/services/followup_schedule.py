"""When is a follow-up visit late?

One definition, shared by the ASHA's own task list and the supervisor's
compliance view, so the two can never disagree about whether a patient was
missed -- an ASHA seeing "due today" while her BMO sees "overdue" would
make the dashboard impossible to trust.

The deadline itself is set per visit by Agent 3 from the risk level (HIGH
48h, MEDIUM 7 days, LOW 30 days -- see FOLLOWUP_DAYS there), so lateness
is already risk-weighted: a HIGH-risk mother shows as missed within two
days, while a LOW-risk one isn't chased for a month.
"""
from datetime import datetime, timezone

OVERDUE = "overdue"
DUE_TODAY = "due_today"
UPCOMING = "upcoming"
UNSCHEDULED = "unscheduled"


def _as_utc(value: datetime) -> datetime:
    """Rows written before timezone-aware storage come back naive. They
    were always UTC, so say so rather than letting a naive/aware compare
    raise in the middle of a dashboard request."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def classify(due_at: datetime | None, now: datetime | None = None) -> tuple[str, int]:
    """Return (bucket, hours_overdue).

    hours_overdue is 0 unless the deadline has passed. Hours rather than
    days because the HIGH-risk window is only 48 of them -- rounding to
    days would report a mother six hours past her deadline as "0 days
    late", which reads as fine when it isn't.
    """
    now = now or datetime.now(timezone.utc)
    if due_at is None:
        return UNSCHEDULED, 0

    due = _as_utc(due_at)
    if due < now:
        return OVERDUE, int((now - due).total_seconds() // 3600)
    if due.date() == now.date():
        return DUE_TODAY, 0
    return UPCOMING, 0


def describe(bucket: str, hours_overdue: int) -> str:
    """Short human phrasing for the same fact, so mobile and web label it
    identically."""
    if bucket != OVERDUE:
        return {DUE_TODAY: "Due today", UPCOMING: "Upcoming", UNSCHEDULED: "No date set"}[bucket]
    if hours_overdue < 24:
        return f"{hours_overdue}h overdue"
    return f"{hours_overdue // 24}d overdue"
