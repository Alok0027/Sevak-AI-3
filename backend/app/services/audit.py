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
