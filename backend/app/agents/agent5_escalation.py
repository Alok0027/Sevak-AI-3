"""Agent 5 -- Escalation (FR-06, FR-03.4).

Not a node in the per-visit graph: a monitor that fires when a HIGH risk
flag has sat unactioned past 48 hours -- plus, separately, an immediate
alert fired the moment a visit classifies HIGH at all.

Two different requirements, two different clocks, deliberately not merged:

  FR-03.4 -- the ANM hears about a HIGH case within 60 seconds, full stop,
  whether or not a follow-up ever gets recorded. This is `immediate_alert`,
  built and sent synchronously inside the same request that created the
  visit (see visit_pipeline.run_voice_visit) -- a 60-second target cannot
  be met by a worker that ticks once a minute, so this one does not wait
  for one.

  FR-06.1 -- if a HIGH case is *still* unactioned 48 hours later, the BMO
  (or ANM) gets paged again. This is `escalation_alert`, built by
  `check_and_escalate` and left pending for the independent outbox worker
  (scripts.process_notifications) to deliver -- a two-day threshold has no
  need to be synchronous, and tying it to the request path would mean a
  district where nobody visits a patient for two days never escalates.

`deliver_escalation_alerts` sends whichever of the two is pending; the
caller decides synchronous vs deferred by choosing when to call it.

An action row rather than a new column on risk_flags, deliberately: the
actions table already carries status/sent_at and is already rendered in
the visit timeline, so an alert that failed to send is visible in the same
place as a referral that failed to send. It also means no schema change,
which matters because this project has no migrations yet (see the
deployment section of the top-level README).
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models.action import Action
from app.db.models.patient import Patient
from app.db.models.risk_flag import RiskFlag
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.services.sms_client import MockSmsClient

logger = logging.getLogger(__name__)

ESCALATION_THRESHOLD_HOURS = 48

# The two alert action types this module produces -- see the module
# docstring for why immediate and 48h-unactioned are kept separate rather
# than one type with two triggers.
ALERT_ACTION_TYPES = ("escalation_alert", "immediate_alert")


def check_and_escalate(db: Session) -> list[str]:
    """FR-06.1: fire escalation for any HIGH risk flag with no recorded
    follow-up action after the 48-hour threshold. Returns escalated flag_ids."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ESCALATION_THRESHOLD_HOURS)
    candidates = (
        db.query(RiskFlag)
        .filter(
            RiskFlag.risk_level == "HIGH",
            RiskFlag.actioned_at.is_(None),
            RiskFlag.escalated_at.is_(None),
            RiskFlag.created_at <= cutoff,
        )
        .all()
    )
    escalated = []
    for flag in candidates:
        claimed = db.query(RiskFlag).filter(RiskFlag.flag_id == flag.flag_id,
            RiskFlag.actioned_at.is_(None), RiskFlag.escalated_at.is_(None)).update(
                {RiskFlag.escalated_at: datetime.now(timezone.utc)}, synchronize_session="fetch")
        if not claimed:
            continue
        alert = _build_alert(db, flag)
        if alert is not None:
            escalated.append(flag.flag_id)
            db.add(alert)
        else:
            flag.escalated_at = None  # Retry recipient lookup after staffing is corrected.
    if candidates:
        db.commit()
    return escalated


def _supervisor_for(db: Session, flag: RiskFlag) -> Worker | None:
    """The ANM covering the sub-centre of the ASHA who raised the flag.

    Falls back to the BMO when a sub-centre has no ANM on record, because
    an alert with no recipient is the same as no alert. Returns None only
    when the deployment has neither, which is a data problem worth seeing
    in the logs rather than papering over.
    """
    visit = db.query(Visit).filter(Visit.visit_id == flag.visit_id).first()
    if visit is None:
        return None
    asha = db.query(Worker).filter(Worker.worker_id == visit.worker_id).first()
    if asha is None:
        return None
    if asha.sub_centre_id:
        anm = (
            db.query(Worker)
            .filter(Worker.role == "anm", Worker.sub_centre_id == asha.sub_centre_id, Worker.status == "active")
            .first()
        )
        if anm is not None:
            return anm
    return db.query(Worker).filter(Worker.role == "bmo", Worker.status == "active").first()


def _build_alert(db: Session, flag: RiskFlag) -> Action | None:
    """One pending escalation_alert action for a newly escalated flag."""
    supervisor = _supervisor_for(db, flag)
    if supervisor is None:
        logger.warning("flag %s escalated with no ANM or BMO to notify", flag.flag_id)
        return None
    visit = db.query(Visit).filter(Visit.visit_id == flag.visit_id).first()
    patient = db.query(Patient).filter(Patient.patient_id == visit.patient_id).first() if visit else None
    name = patient.name if patient else "a patient"
    hours = int(ESCALATION_THRESHOLD_HOURS)
    return Action(
        visit_id=flag.visit_id,
        type="escalation_alert",
        content=(
            f"{name} was flagged HIGH risk and has had no follow-up action "
            f"for over {hours} hours. {supervisor.name} ({supervisor.role.upper()}) "
            f"needs to review this today."
        ),
        status="pending",
    )


def build_immediate_alert(db: Session, flag: RiskFlag) -> Action | None:
    """FR-03.4: one pending immediate_alert for a HIGH flag just raised.

    Distinct action type from `_build_alert`'s escalation_alert (see the
    module docstring): this one is not gated by escalated_at or the
    48-hour threshold at all, because it fires once, right away, for every
    HIGH classification -- a case can get this alert now and the 48-hour
    one later if it is still untouched, and the two must not suppress or
    double-count each other.
    """
    supervisor = _supervisor_for(db, flag)
    if supervisor is None:
        logger.warning("flag %s classified HIGH with no ANM or BMO to notify", flag.flag_id)
        return None
    visit = db.query(Visit).filter(Visit.visit_id == flag.visit_id).first()
    patient = db.query(Patient).filter(Patient.patient_id == visit.patient_id).first() if visit else None
    name = patient.name if patient else "a patient"
    return Action(
        visit_id=flag.visit_id,
        type="immediate_alert",
        content=(
            f"{name} was just flagged HIGH risk. {supervisor.name} "
            f"({supervisor.role.upper()}) should review this as soon as possible."
        ),
        status="pending",
    )


async def deliver_escalation_alerts(db: Session, whatsapp_client=None, sms_client=None) -> int:
    """Send every pending alert -- both immediate_alert and escalation_alert.
    Returns how many went out.

    Failures are recorded on the action as status "failed" rather than
    raised: this can run at the tail of a visit (see visit_pipeline), and a
    supervisor's phone being unreachable must not fail the ASHA's visit.
    The row stays visible, so a persistent failure shows up as a column of
    "failed" alerts rather than as silence.
    """
    pending = (
        db.query(Action)
        .filter(Action.type.in_(ALERT_ACTION_TYPES), Action.status == "pending")
        .all()
    )
    if not pending:
        return 0

    sent = 0
    for action in pending:
        flag = (
            db.query(RiskFlag)
            .filter(RiskFlag.visit_id == action.visit_id, RiskFlag.risk_level == "HIGH")
            .first()
        )
        supervisor = _supervisor_for(db, flag) if flag is not None else None
        if supervisor is None or not supervisor.phone:
            action.status = "failed"
            continue
        try:
            if sms_client is not None and not isinstance(sms_client, MockSmsClient):
                await sms_client.send_message(supervisor.phone, action.content)
            elif whatsapp_client is not None:
                await whatsapp_client.send_message(supervisor.phone, action.content)
            else:
                # No real channel configured. The alert stays pending rather
                # than being marked sent, so turning SMS on later delivers
                # the backlog instead of losing it.
                continue
            action.status = "sent"
            action.sent_at = datetime.now(timezone.utc)
            sent += 1
        except Exception as exc:  # noqa: BLE001 -- see docstring
            logger.warning("escalation alert to %s failed: %s", supervisor.role, exc)
            action.status = "failed"
    db.commit()
    return sent


def get_pending_escalations(db: Session, sub_centre_id: str | list[str] | None = None) -> list[dict]:
    """FR-06.2: BMO/ANM dashboard feed -- all unactioned HIGH risk cases
    sorted by time elapsed since flag, regardless of whether the 48h
    auto-escalation has fired yet (so a supervisor sees it coming, not just
    after the threshold). `sub_centre_id` scopes an ANM to their own
    sub-centre (SRS table 4); leave None for BMO/Admin's district-wide view.
    Enriched with patient/worker context so the dashboard doesn't have to
    show a bare name with no way to judge severity."""
    import json

    now = datetime.now(timezone.utc)
    query = (
        db.query(RiskFlag, Visit, Patient, Worker)
        .join(Visit, RiskFlag.visit_id == Visit.visit_id)
        .join(Patient, Visit.patient_id == Patient.patient_id)
        .join(Worker, Visit.worker_id == Worker.worker_id)
        .filter(RiskFlag.risk_level == "HIGH", RiskFlag.actioned_at.is_(None))
    )
    if isinstance(sub_centre_id, str):
        query = query.filter(Worker.sub_centre_id == sub_centre_id)
    elif sub_centre_id is not None:
        # A BMO is scoped to her district's sub-centres, not to one of
        # them; an empty list is "nothing in scope", not "everything".
        query = query.filter(Worker.sub_centre_id.in_(sub_centre_id))

    results = []
    for flag, visit, patient, worker in query.all():
        created = flag.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        hours_elapsed = (now - created).total_seconds() / 3600
        drivers = []
        citations = []
        if flag.drivers_json:
            try:
                parsed = json.loads(flag.drivers_json)
                drivers = [d.get("reason", "") for d in parsed]
                # The NHM documents behind those reasons, deduplicated:
                # two drivers citing the same guideline section is one
                # source, and listing it twice reads as two independent
                # confirmations when it is one.
                #
                # Carried beside `drivers` rather than folded into it
                # because `drivers` is a list of strings in the API
                # contract and the dashboard renders it as one; adding a
                # field is additive, changing that one is not.
                seen = set()
                for d in parsed:
                    label = d.get("source")
                    if label and label not in seen:
                        seen.add(label)
                        citations.append({"label": label, "url": d.get("source_url") or ""})
            except (ValueError, AttributeError):
                drivers = []
                citations = []
        results.append(
            {
                "patient": patient.name,
                "patient_id": patient.patient_id,
                "patient_age": patient.age,
                "patient_village": patient.village,
                "flag_time": flag.created_at.isoformat(),
                "hours_elapsed": round(hours_elapsed, 1),
                "worker": worker.name,
                "worker_id": worker.worker_id,
                "worker_sub_centre": worker.sub_centre_id,
                "visit_id": visit.visit_id,
                "drivers": drivers,
                "citations": citations,
            }
        )
    results.sort(key=lambda r: r["hours_elapsed"], reverse=True)
    return results
