import json
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy import case
from app.api.deps import DbSession, require_roles
from app.core.config import get_settings
from app.db.models.action import Action
from app.db.models.visit import Visit
from app.db.models.patient import Patient
from app.db.models.notification import Notification
from app.services.notifications import preview
from app.db.models.audit_log import AuditLog
from app.services.audit import record_read as audit_read

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

class Approval(BaseModel):
    channel: Literal["sms", "whatsapp"]
    preview_hash: str
    consent_confirmed: bool

def owned(db, action_id, user):
    row = db.query(Action, Visit, Patient).join(Visit, Action.visit_id == Visit.visit_id).join(
        Patient, Visit.patient_id == Patient.patient_id).filter(Action.action_id == action_id,
        Action.type == "whatsapp", Visit.worker_id == user.worker_id).first()
    if row is None:
        raise HTTPException(404, "Notification not found")
    return row

@router.get("")
def list_notifications(db: DbSession, user=Depends(require_roles("asha"))):
    rows = db.query(Action, Visit, Patient).join(Visit, Action.visit_id == Visit.visit_id).join(
        Patient, Visit.patient_id == Patient.patient_id).filter(Visit.worker_id == user.worker_id,
        Action.type == "whatsapp").order_by(
            case((Action.status == "draft", 0), (Action.status == "needs_review", 1), else_=2),
            Action.created_at.desc()).limit(100).all()
    audit_read(db, user.worker_id, user.worker_id, "patient_notification", count=len(rows))
    return {"notifications": [{"action_id": a.action_id, "patient": p.name,
        "status": a.status, "content": a.content} for a, v, p in rows]}

@router.get("/{action_id}/preview")
def notification_preview(action_id: str, db: DbSession, channel: Literal["sms", "whatsapp"] = "whatsapp",
                         user=Depends(require_roles("asha"))):
    a, v, p = owned(db, action_id, user)
    payload, digest = preview(a, v, p, channel, get_settings())
    # This one discloses the patient's phone number, not just her name.
    audit_read(db, user.worker_id, p.patient_id, "patient_contact")
    return {"text": payload["text"], "phone": payload["phone"], "preview_hash": digest, "channel": channel}

@router.post("/{action_id}/approve")
def approve(action_id: str, payload: Approval, db: DbSession, user=Depends(require_roles("asha"))):
    a, v, p = owned(db, action_id, user)
    existing = db.get(Notification, action_id)
    if existing:
        return {"status": existing.status}
    if a.status != "draft" or not payload.consent_confirmed:
        raise HTTPException(409, "Draft notification and patient consent confirmation required")
    data, digest = preview(a, v, p, payload.channel, get_settings())
    if digest != payload.preview_hash:
        raise HTTPException(409, "Message or recipient changed; review the preview again")
    db.add(Notification(action_id=action_id, payload_json=json.dumps(data), approved_by=user.worker_id))
    a.status = "queued"
    a.content = data["text"]
    db.add(AuditLog(user_id=user.worker_id, action_type="notification.approve", record_id=action_id,
        record_type="action", details=json.dumps({"channel": payload.channel, "preview_hash": digest, "consent_confirmed": True})))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": db.get(Notification, action_id).status}
    return {"status": "queued"}
