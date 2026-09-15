"""Who to see first.

Colour already says *what* a patient is. Nothing said *when*. A HIGH-risk
mother sitting at row 47 of an ASHA's list was correctly coloured and still
missed, because a list with no opinion about order asks the reader to hold
sixty rows in their head and pick.

Order is the strongest signal a list has -- stronger than a badge, a chip,
or a tint, and it costs no pixels. So this module decides the order, once,
on the server, and every surface reads it: the ASHA's patient list, the
ANM's sub-centre view, the BMO's district table. A supervisor and the
worker she supervises must never be looking at differently-ordered copies
of the same ward.

The scoring rests on something the system already gets right. Agent 3 sets
each follow-up's deadline *from* the risk level -- HIGH 48 hours, MEDIUM 7
days, LOW 30 days (agent3_action_generation.FOLLOWUP_DAYS). So "overdue" is
already risk-weighted: a HIGH mother is late after two days, a LOW one
isn't chased for a month. That makes lateness an honest primary signal
rather than a second, competing one, and it is why an overdue LOW does not
leapfrog a HIGH: her thirty-day window was generous precisely because she
is well.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services import followup_schedule

# Why a patient is in today's work. Returned as a key, not a sentence: the
# mobile app says it in six languages and the dashboard says it in English,
# and neither should be re-translating a phrase the server made up.
HIGH_RISK = "high_risk"
OVERDUE = "overdue"
DUE_TODAY = "due_today"

# Severity, before lateness is considered.
#
# UNASSESSED sits above MEDIUM and below HIGH on purpose. It is not a
# fourth grade of illness -- it means the visit produced nothing the
# classifier could read, so the honest statement is "nobody knows how she
# is". An unknown outranks a mild known finding, because a mild finding has
# at least been looked at. It stays below HIGH because a measured
# emergency beats an unmeasured maybe.
_SEVERITY = {
    "HIGH": 100,
    "UNASSESSED": 45,
    "MEDIUM": 30,
    "LOW": 0,
}

# Being late is worth roughly a grade and a half of severity, so a MEDIUM
# that has been missed (30 + 50) outranks a MEDIUM that has not (30), and
# still sits below a HIGH seen on time (100). That is the intended
# reading: lateness escalates, it does not outrank the clinical picture.
_OVERDUE_BASE = 50
_DUE_TODAY_BONUS = 20

# Each further day late adds a little, so a queue of overdue patients
# sorts worst-first instead of arbitrarily. Capped at a fortnight: past
# that the list stops being a schedule and becomes a backlog, and letting
# a 90-day lapse dominate would bury this week's genuinely urgent work
# underneath somebody who has already been missed for a season.
_PER_DAY_LATE = 2
_MAX_DAYS_COUNTED = 14


@dataclass(frozen=True)
class Priority:
    score: int
    needs_attention: bool
    # HIGH_RISK | OVERDUE | DUE_TODAY | None
    reason: str | None
    hours_overdue: int


def assess(
    risk_level: str | None,
    followup_due_at: datetime | None,
    *,
    has_open_followup: bool = True,
    now: datetime | None = None,
) -> Priority:
    """Rank one patient.

    [followup_due_at] is her *earliest still-open* follow-up. Earliest, not
    latest: a mother with one visit two days late and another due next week
    is two days late, and taking the later date would quietly retire the
    lapse.

    [has_open_followup] false means every follow-up is done, or she has
    never been visited. Her risk still counts -- a HIGH mother whose
    follow-up was completed yesterday is still a HIGH mother -- but there
    is no deadline to be late for.
    """
    severity = _SEVERITY.get(risk_level or "", 0)

    bucket, hours_overdue = (
        followup_schedule.classify(followup_due_at, now)
        if has_open_followup
        else (followup_schedule.UNSCHEDULED, 0)
    )

    score = severity
    reason: str | None = None

    if bucket == followup_schedule.OVERDUE:
        days_late = min(hours_overdue // 24, _MAX_DAYS_COUNTED)
        score += _OVERDUE_BASE + days_late * _PER_DAY_LATE
        reason = OVERDUE
    elif bucket == followup_schedule.DUE_TODAY:
        score += _DUE_TODAY_BONUS
        reason = DUE_TODAY

    # HIGH names itself, even when nothing is late. A mother flagged HIGH
    # this morning has no overdue anything and is still the first door to
    # knock on.
    if risk_level == "HIGH" and reason is None:
        reason = HIGH_RISK

    # What belongs in today's work, as opposed to merely sorting high.
    #
    # Two separate questions, deliberately. The score answers "how bad";
    # this answers "is it mine to do today", and the answer is the same one
    # the task board already gives (routes/tasks.py): anything HIGH, plus
    # anything she has actually promised and not delivered. An overdue LOW
    # is a broken commitment even though she is well, so it is today's work
    # even though it sorts near the bottom of today's work.
    attention = risk_level == "HIGH" or bucket in (
        followup_schedule.OVERDUE,
        followup_schedule.DUE_TODAY,
    )

    return Priority(
        score=score,
        needs_attention=attention,
        reason=reason if attention else None,
        hours_overdue=hours_overdue,
    )
