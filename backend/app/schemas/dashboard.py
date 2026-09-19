from datetime import datetime

from pydantic import BaseModel


class FollowupDue(BaseModel):
    """One *patient* an ASHA owes a visit, and how late the most urgent
    reason to go is.

    One row per person, not per pending action row. An ASHA walks to a
    house and a supervisor chases a name: a patient with forty
    outstanding follow-ups is still one doorstep and one phone call.
    Listing her forty times buries every other patient in the sub-centre
    and makes the table read as a single repeated name.

    `also_pending` counts the *other* follow-ups waiting at the same
    address, so the collapse hides nothing; every field above it
    describes the most urgent one."""

    action_id: str
    visit_id: str
    patient_id: str
    patient_name: str
    village: str | None = None
    risk_level: str
    due_at: datetime | None = None
    bucket: str  # overdue | due_today | upcoming | unscheduled
    hours_overdue: int = 0
    label: str  # "3d overdue" / "Due today" -- phrased once, server-side
    content: str
    also_pending: int = 0


class WorkerFollowupCompliance(BaseModel):
    """One ASHA's outstanding visits.

    Workers with nothing outstanding are still listed, with zero counts: a
    supervisor needs to see that everyone is accounted for, not only who
    is in trouble. An absent row is ambiguous -- no work, or no data?

    The counts are *patients*, matching the rows in `visits`. A count of
    pending action rows would disagree with the list underneath it, and a
    supervisor comparing "228 overdue" against four visible names would
    reasonably conclude the page was broken. `total_pending_actions`
    keeps the raw workload figure available for anyone who wants it.
    """

    worker_id: str
    worker_name: str
    sub_centre_id: str | None = None
    overdue: int = 0
    due_today: int = 0
    upcoming: int = 0
    total_pending_actions: int = 0
    visits: list[FollowupDue] = []


class FollowupComplianceResponse(BaseModel):
    as_of: datetime
    total_overdue: int
    total_due_today: int
    total_upcoming: int
    workers: list[WorkerFollowupCompliance]


class RiskPoint(BaseModel):
    """One village on the district heatmap.

    This used to be one row per (village, risk_level) pair, which drew
    two or three dots on top of each other at the same coordinate: the
    HIGH one covered the others, so a village with 1 HIGH and 40 LOW
    looked exactly like a village with 1 HIGH and nothing else. One row
    per village with the split carried alongside is what a supervisor is
    actually reading the map for.

    The three counts are patients, not visits, and they are split by each
    patient's *latest* visit -- so they sum to patient_count and answer
    "how many women here are HIGH risk right now", not "how many HIGH
    readings has this village ever produced".
    """

    lat: float
    lng: float
    risk_level: str  # worst level currently open in the village
    patient_count: int
    village: str | None = None
    visit_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    last_visit_at: datetime | None = None
    # False only for a village in the gazetteer (app/services/geo.py). A
    # placeholder position is labelled as one on the map rather than
    # passed off as a survey coordinate.
    approximate_location: bool = False


class HeatmapResponse(BaseModel):
    risk_points: list[RiskPoint]


class DashboardMetrics(BaseModel):
    """FR-08.2: the four headline metrics."""

    total_visits_today: int
    high_risk_cases: int
    pending_followups: int
    hmis_completion_rate: float  # 0.0 - 1.0


class Citation(BaseModel):
    label: str          # "<document title> — <section>"
    url: str = ""


class EscalationItem(BaseModel):
    patient: str
    patient_id: str
    patient_age: int | None = None
    patient_village: str | None = None
    flag_time: str
    hours_elapsed: float
    worker: str
    worker_id: str
    worker_sub_centre: str | None = None
    visit_id: str
    drivers: list[str] = []
    # The NHM guideline sections those drivers were grounded on, when
    # Agent 2 classified with retrieval. Empty for a flag raised by the
    # threshold engine alone, and for every flag recorded before the
    # corpus existed -- so the dashboard must treat empty as "no citation
    # available", never as "unsourced and therefore suspect".
    citations: list[Citation] = []


class DayCount(BaseModel):
    date: str  # YYYY-MM-DD
    count: int


class RiskBreakdown(BaseModel):
    high: int
    medium: int
    low: int


class FollowupStatus(BaseModel):
    done: int
    pending: int
    overdue: int  # pending + due_at in the past


class WorkerLeaderboardEntry(BaseModel):
    worker_id: str
    worker_name: str
    total_visits: int
    high_risk_count: int


class DashboardAnalytics(BaseModel):
    visits_by_day: list[DayCount]
    risk_breakdown: RiskBreakdown
    followup_status: FollowupStatus
    worker_leaderboard: list[WorkerLeaderboardEntry]
