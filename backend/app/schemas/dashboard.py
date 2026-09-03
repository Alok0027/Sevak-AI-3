from pydantic import BaseModel


class RiskPoint(BaseModel):
    lat: float
    lng: float
    risk_level: str
    patient_count: int
    village: str | None = None


class HeatmapResponse(BaseModel):
    risk_points: list[RiskPoint]


class DashboardMetrics(BaseModel):
    """FR-08.2: the four headline metrics."""

    total_visits_today: int
    high_risk_cases: int
    pending_followups: int
    hmis_completion_rate: float  # 0.0 - 1.0


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
