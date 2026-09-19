"""GET /api/v1/dashboard/{heatmap,metrics,analytics} (FR-08.1, FR-08.2).

Every number below is a real query result -- no placeholder or randomly
generated figures. ANM callers are automatically scoped to their own
sub_centre_id (SRS table 4); BMO/Admin see the whole district.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Query as SAQuery, Session

from app.api.deps import DbSession, require_roles, visible_sub_centres
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
from app.services import followup_schedule, geo

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

TREND_WINDOW_DAYS = 14

# Ranked worst-first: the map's colour, and the order the legend reads in.
_RISK_ORDER = ("HIGH", "MEDIUM", "LOW")


def _due_sort(due_at: datetime | None) -> datetime:
    """Sort key for a nullable deadline. An unscheduled follow-up sorts
    last rather than crashing the comparison or jumping to the top."""
    if due_at is None:
        return datetime.max.replace(tzinfo=timezone.utc)
    return due_at if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)


def _scoped_visits(db: Session, scope: list[str] | None) -> SAQuery:
    """Base Visit query, joined to Worker and filtered to the sub-centres
    the caller may see (one for an ANM, her district's for a BMO, all for
    an Admin -- see deps.visible_sub_centres)."""
    q = db.query(Visit).join(Worker, Visit.worker_id == Worker.worker_id)
    if scope is not None:
        q = q.filter(Worker.sub_centre_id.in_(scope))
    return q


@router.get("/heatmap", response_model=HeatmapResponse)
def heatmap(
    db: DbSession,
    user=Depends(require_roles("anm", "bmo", "admin")),
    district_id: str | None = Query(default=None),
    date_range: str | None = Query(default=None),
) -> HeatmapResponse:
    """One point per village: how many patients, how they currently split
    across HIGH/MEDIUM/LOW, and when the village was last visited.

    The split is by each patient's most recent classified visit, so the
    three counts sum to patient_count and describe the village as it
    stands today -- a woman flagged HIGH in March and cleared in April
    counts once, as LOW. Counting every visit instead (which is what this
    endpoint used to do, while calling the result `patient_count`) made a
    frequently-visited village look like a dangerous one.

    ponytail: aggregation happens in Python over the scoped visit rows
    rather than in SQL, matching the rest of this module. That is fine
    for a district pilot (tens of thousands of rows at most); the upgrade
    path if a state-wide deployment ever needs it is a GROUP BY with a
    window function for the per-patient latest visit.
    """
    scope = visible_sub_centres(user, db)
    # The caller's own district, so a village the gazetteer doesn't know
    # is placed inside it rather than somewhere else in the state.
    me = db.query(Worker).filter(Worker.worker_id == user.worker_id).first()
    district = me.district_id if me else None
    rows = (
        _scoped_visits(db, scope)
        .join(Patient, Visit.patient_id == Patient.patient_id)
        .filter(Visit.risk_level.isnot(None))
        .with_entities(Patient.village, Visit.patient_id, Visit.risk_level, Visit.created_at)
        .all()
    )

    villages: dict[str, dict] = {}
    for village, patient_id, risk_level, created_at in rows:
        name = village or "Unknown"
        when = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        entry = villages.setdefault(name, {"visits": 0, "last_visit_at": None, "latest": {}})
        entry["visits"] += 1
        if entry["last_visit_at"] is None or when > entry["last_visit_at"]:
            entry["last_visit_at"] = when
        seen = entry["latest"].get(patient_id)
        if seen is None or when > seen[0]:
            entry["latest"][patient_id] = (when, risk_level)

    points = []
    for name, entry in villages.items():
        levels = [level for _, level in entry["latest"].values()]
        counts = {level: levels.count(level) for level in _RISK_ORDER}
        lat, lng, approximate = geo.locate(name, district)
        points.append(
            RiskPoint(
                lat=lat,
                lng=lng,
                village=name,
                approximate_location=approximate,
                # Worst level still open here. Anything the classifier
                # couldn't score (UNASSESSED) is carried in patient_count
                # but never colours the dot -- it isn't a severity.
                risk_level=next((lvl for lvl in _RISK_ORDER if counts[lvl]), "LOW"),
                patient_count=len(entry["latest"]),
                visit_count=entry["visits"],
                high_count=counts["HIGH"],
                medium_count=counts["MEDIUM"],
                low_count=counts["LOW"],
                last_visit_at=entry["last_visit_at"],
            )
        )

    # Worst first, then biggest: the order the dashboard draws them in, so
    # a HIGH village's dot lands on top of its quieter neighbours rather
    # than under them.
    points.sort(key=lambda p: (_RISK_ORDER.index(p.risk_level), -p.patient_count))
    return HeatmapResponse(risk_points=points)


@router.get("/metrics", response_model=DashboardMetrics)
def metrics(
    db: DbSession,
    user=Depends(require_roles("anm", "bmo", "admin")),
) -> DashboardMetrics:
    scope = visible_sub_centres(user, db)
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
    if scope is not None:
        pending_followups_q = pending_followups_q.filter(Worker.sub_centre_id.in_(scope))
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
    scope = visible_sub_centres(user, db)
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
    if scope is not None:
        followup_q = followup_q.filter(Worker.sub_centre_id.in_(scope))
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
    scope = visible_sub_centres(user, db)
    now = datetime.now(timezone.utc)

    workers = db.query(Worker).filter(Worker.role == "asha")
    if scope is not None:
        workers = workers.filter(Worker.sub_centre_id.in_(scope))
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
