"""NFR-SC4: audit log on every data access/modification."""
import json

from sqlalchemy.orm import Session

from app.db.models.audit_log import AuditLog


def record(
    db: Session,
    user_id: str,
    action_type: str,
    record_id: str | None = None,
    record_type: str | None = None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> None:
    entry = AuditLog(
        user_id=user_id,
        action_type=action_type,
        record_id=record_id,
        record_type=record_type,
        ip_address=ip_address,
        details=json.dumps(details) if details is not None else None,
    )
    db.add(entry)
    db.commit()


def record_read(
    db: Session,
    user_id: str,
    record_id: str | None,
    record_type: str,
    *,
    count: int | None = None,
    ip_address: str | None = None,
) -> None:
    """NFR-SC4's other half: log that someone *looked*, not just that they changed.

    Until this existed the audit table held writes and logins only, so a
    supervisor could read every patient record in her district and leave no
    trace. Under the DPDP Act access is the event that matters for patient
    data -- a record that is only ever read is still a record that was
    disclosed.

    Scope is deliberate and worth stating, because the alternative is a
    table nobody can read:

      - Reads that resolve to identifiable patients are logged: a patient's
        history, a worker's patient list, the patient directory, a task
        list naming patients.
      - The auto-refreshing supervisor views are not. The dashboard polls
        metrics, the heatmap and the escalation queue every 60 seconds by
        design, so logging those records the browser's refresh timer rather
        than a person's decision -- ~1,400 rows per supervisor per day,
        burying the accesses that mean something. The metrics and heatmap
        endpoints return aggregates with no names in them at all; the
        escalation queue does name patients, and the access worth auditing
        there is the moment she opens one, which is a patient-history read
        and is logged.

    `count` records how many patients a list read exposed, so "opened one
    record" and "listed four hundred" are distinguishable after the fact.
    """
    details = {"count": count} if count is not None else None
    record(
        db,
        user_id=user_id,
        action_type=f"{record_type}.read",
        record_id=record_id,
        record_type=record_type,
        ip_address=ip_address,
        details=details,
    )
