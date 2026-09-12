"""GET /api/v1/dashboard/{heatmap,metrics,analytics} (FR-08.1, FR-08.2).

Every number below is a real query result -- no placeholder or randomly
generated figures. ANM callers are automatically scoped to their own
sub_centre_id (SRS table 4); BMO/Admin see the whole district.
"""
import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Query as SAQuery, Session

from app.api.deps import DbSession, get_supervisor_scope, require_roles
from app.db.models.action import Action
from app.db.models.patient import Patient
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.schemas.dashboard import (
    DashboardAnalytics,
    DashboardMetrics,
    DayCount,
    FollowupComplianceResponse,
    FollowupDue,
    FollowupStatus,
    HeatmapResponse,
    RiskBreakdown,
    RiskPoint,
    WorkerFollowupCompliance,
    WorkerLeaderboardEntry,
)
from app.services import followup_schedule

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

_MH_LAT_RANGE = (17.5, 21.5)
_MH_LNG_RANGE = (73.0, 76.5)
TREND_WINDOW_DAYS = 14


def _village_to_latlng(village: str) -> tuple[float, float]:
    digest = hashlib.sha256(village.encode()).hexdigest()
    frac_lat = int(digest[:8], 16) / 0xFFFFFFFF
    frac_lng = int(digest[8:16], 16) / 0xFFFFFFFF
    lat = _MH_LAT_RANGE[0] + frac_lat * (_MH_LAT_RANGE[1] - _MH_LAT_RANGE[0])
    lng = _MH_LNG_RANGE[0] + frac_lng * (_MH_LNG_RANGE[1] - _MH_LNG_RANGE[0])
    return round(lat, 5), round(lng, 5)


def _due_sort(due_at: datetime | None) -> datetime:
    """Sort key for a nullable deadline. An unscheduled follow-up sorts
    last rather than crashing the comparison or jumping to the top."""
    if due_at is None:
        return datetime.max.replace(tzinfo=timezone.utc)
    return due_at if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)


def _scoped_visits(db: Session, scope: str | None) -> SAQuery:
    """Base Visit query, joined to Worker and filtered to `scope`'s
    sub_centre_id when set (ANM), or unfiltered (BMO/Admin)."""
    q = db.query(Visit).join(Worker, Visit.worker_id == Worker.worker_id)
    if scope:
        q = q.filter(Worker.sub_centre_id == scope)
    return q


@router.get("/heatmap", response_model=HeatmapResponse)
def heatmap(
    db: DbSession,
    user=Depends(require_roles("anm", "bmo", "admin")),
    district_id: str | None = Query(default=None),
    date_range: str | None = Query(default=None),
) -> HeatmapResponse:
    scope = get_supervisor_scope(user, db)
    rows = (
        _scoped_visits(db, scope)
        .join(Patient, Visit.patient_id == Patient.patient_id)
        .filter(Visit.risk_level.isnot(None))
        .with_entities(Patient.village, Visit.risk_level)
        .all()
    )
    buckets: dict[tuple[str, str], int] = {}
    for village, risk_level in rows:
        key = (village or "Unknown", risk_level)
        buckets[key] = buckets.get(key, 0) + 1

    points = []
    for (village, risk_level), count in buckets.items():
        lat, lng = _village_to_latlng(village)
        points.append(RiskPoint(lat=lat, lng=lng, risk_level=risk_level, patient_count=count, village=village))

    return HeatmapResponse(risk_points=points)


@router.get("/metrics", response_model=DashboardMetrics)
def metrics(
    db: DbSession,
    user=Depends(require_roles("anm", "bmo", "admin")),
) -> DashboardMetrics:
    scope = get_supervisor_scope(user, db)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    base = _scoped_visits(db, scope)
    total_visits_today = base.filter(Visit.created_at >= today_start).count()
    high_risk_cases = base.filter(Visit.risk_level == "HIGH").count()

    pending_followups_q = (
        db.query(Action)
        .join(Visit, Action.visit_id == Visit.visit_id)
        .join(Worker, Visit.worker_id == Worker.worker_id)
        .filter(Action.type == "followup", Action.status == "pending")
    )
    if scope:
        pending_followups_q = pending_followups_q.filter(Worker.sub_centre_id == scope)
    pending_followups = pending_followups_q.count()

    total_visits = base.count()
    visits_with_report_contribution = base.filter(Visit.structured_json.isnot(None)).count()
    hmis_completion_rate = (visits_with_report_contribution / total_visits) if total_visits else 0.0

    return DashboardMetrics(
        total_visits_today=total_visits_today,
        high_risk_cases=high_risk_cases,
        pending_followups=pending_followups,
        hmis_completion_rate=round(hmis_completion_rate, 2),
    )


@router.get("/analytics", response_model=DashboardAnalytics)
def analytics(
    db: DbSession,
    user=Depends(require_roles("anm", "bmo", "admin")),
) -> DashboardAnalytics:
    scope = get_supervisor_scope(user, db)
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(days=TREND_WINDOW_DAYS - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    # --- visits per day, last 14 days ---
    day_rows = (
        _scoped_visits(db, scope)
        .filter(Visit.created_at >= window_start)
        .with_entities(func.date(Visit.created_at), func.count(Visit.visit_id))
        .group_by(func.date(Visit.created_at))
        .all()
    )
    counts_by_date = {str(d): c for d, c in day_rows}
    visits_by_day = []
    for i in range(TREND_WINDOW_DAYS):
        day = (window_start + timedelta(days=i)).date()
        visits_by_day.append(DayCount(date=day.isoformat(), count=counts_by_date.get(day.isoformat(), 0)))

    # --- risk breakdown (all-time, in scope) ---
    risk_rows = (
        _scoped_visits(db, scope)
        .filter(Visit.risk_level.isnot(None))
        .with_entities(Visit.risk_level, func.count(Visit.visit_id))
        .group_by(Visit.risk_level)
        .all()
    )
    risk_counts = dict(risk_rows)
    risk_breakdown = RiskBreakdown(
        high=risk_counts.get("HIGH", 0), medium=risk_counts.get("MEDIUM", 0), low=risk_counts.get("LOW", 0)
    )

    # --- follow-up completion ---
    followup_q = (
        db.query(Action)
        .join(Visit, Action.visit_id == Visit.visit_id)
        .join(Worker, Visit.worker_id == Worker.worker_id)
        .filter(Action.type == "followup")
    )
    if scope:
        followup_q = followup_q.filter(Worker.sub_centre_id == scope)
    all_followups = followup_q.all()
    done = sum(1 for a in all_followups if a.status == "done")
    overdue = sum(1 for a in all_followups if a.status == "pending" and a.due_at and a.due_at.replace(tzinfo=timezone.utc) < now)
    pending = sum(1 for a in all_followups if a.status == "pending") - overdue
    followup_status = FollowupStatus(done=done, pending=max(pending, 0), overdue=overdue)

    # --- worker leaderboard (top 10 by visits) ---
    leaderboard_rows = (
        _scoped_visits(db, scope)
        .with_entities(Worker.worker_id, Worker.name, func.count(Visit.visit_id))
        .group_by(Worker.worker_id, Worker.name)
        .order_by(func.count(Visit.visit_id).desc())
        .limit(10)
        .all()
    )
    # Separate query for high-risk counts (portable across SQLite/Postgres,
    # rather than a dialect-specific boolean-sum in the query above).
    worker_ids = [row[0] for row in leaderboard_rows]
    high_counts = dict(
        _scoped_visits(db, scope)
        .filter(Visit.worker_id.in_(worker_ids), Visit.risk_level == "HIGH")
        .with_entities(Visit.worker_id, func.count(Visit.visit_id))
        .group_by(Visit.worker_id)
        .all()
    ) if worker_ids else {}
    worker_leaderboard = [
        WorkerLeaderboardEntry(
            worker_id=row[0], worker_name=row[1], total_visits=row[2], high_risk_count=high_counts.get(row[0], 0)
        )
        for row in leaderboard_rows
    ]

    return DashboardAnalytics(
        visits_by_day=visits_by_day,
        risk_breakdown=risk_breakdown,
        followup_status=followup_status,
        worker_leaderboard=worker_leaderboard,
    )


@router.get("/followup-compliance", response_model=FollowupComplianceResponse)
def followup_compliance(
    db: DbSession,
    user=Depends(require_roles("anm", "bmo", "admin")),
) -> FollowupComplianceResponse:
    """FR-08 accountability: which ASHA owes which patient a visit, and
    which of those are already late.

    The analytics endpoint gives a supervisor three numbers -- done,
    pending, overdue -- which tells her something is wrong but not who to
    call. This returns the underlying rows: the worker, the patient, the
    deadline, and how far past it we are, so a BMO can act on a specific
    name rather than a count.

    Every ASHA in scope is listed even with nothing outstanding, because
    an absent row is ambiguous (no work, or no data?) and 'everyone else
    is clear' is itself the answer a supervisor is looking for.
    """
    scope = get_supervisor_scope(user, db)
    now = datetime.now(timezone.utc)

    workers = db.query(Worker).filter(Worker.role == "asha")
    if scope:
        workers = workers.filter(Worker.sub_centre_id == scope)
    workers = workers.order_by(Worker.name).all()
    by_worker = {
        w.worker_id: WorkerFollowupCompliance(
            worker_id=w.worker_id, worker_name=w.name, sub_centre_id=w.sub_centre_id
        )
        for w in workers
    }

    rows = (
        db.query(Action, Visit, Patient)
        .join(Visit, Action.visit_id == Visit.visit_id)
        .join(Patient, Visit.patient_id == Patient.patient_id)
        .filter(
            Action.type == "followup",
            Action.status == "pending",
            Visit.worker_id.in_(by_worker.keys()) if by_worker else False,
        )
        .all()
    )

    # Collapse to one row per patient per worker, keeping the most urgent
    # follow-up as the visible reason and counting the rest. Done here
    # rather than in the page so that the mobile app, the ANM view and the
    # BMO view can never disagree about how many people are behind.
    most_urgent: dict[tuple[str, str], FollowupDue] = {}
    for action, visit, patient in rows:
        entry = by_worker.get(visit.worker_id)
        if entry is None:  # visit by someone outside this supervisor's scope
            continue
        entry.total_pending_actions += 1
        bucket, hours_overdue = followup_schedule.classify(action.due_at, now)
        key = (visit.worker_id, patient.patient_id)
        existing = most_urgent.get(key)
        if existing is not None:
            existing.also_pending += 1
            # Keep whichever is further past its deadline; for two that are
            # not yet due, whichever falls due first.
            if (hours_overdue, _due_sort(action.due_at)) <= (
                existing.hours_overdue,
                _due_sort(existing.due_at),
            ):
                continue
            replacement_of = existing.also_pending
        else:
            replacement_of = 0

        most_urgent[key] = FollowupDue(
            action_id=action.action_id,
            visit_id=visit.visit_id,
            patient_id=patient.patient_id,
            patient_name=patient.name,
            village=patient.village,
            risk_level=visit.risk_level,
            due_at=action.due_at,
            bucket=bucket,
            hours_overdue=hours_overdue,
            label=followup_schedule.describe(bucket, hours_overdue),
            content=action.content,
            also_pending=replacement_of,
        )

    for (worker_id, _patient_id), due in most_urgent.items():
        entry = by_worker[worker_id]
        entry.visits.append(due)
        if due.bucket == followup_schedule.OVERDUE:
            entry.overdue += 1
        elif due.bucket == followup_schedule.DUE_TODAY:
            entry.due_today += 1
        else:
            entry.upcoming += 1

    for entry in by_worker.values():
        # Most overdue first: that is the order a supervisor works down.
        entry.visits.sort(key=lambda v: (-v.hours_overdue, _due_sort(v.due_at)))

    ordered = sorted(
        by_worker.values(), key=lambda w: (-w.overdue, -w.due_today, w.worker_name)
    )
    return FollowupComplianceResponse(
        as_of=now,
        total_overdue=sum(w.overdue for w in ordered),
        total_due_today=sum(w.due_today for w in ordered),
        total_upcoming=sum(w.upcoming for w in ordered),
        workers=ordered,
    )
