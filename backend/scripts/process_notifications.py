"""Run once per minute from an external scheduler: python -m scripts.process_notifications.

Not started inside the web process. Requires an always-on scheduler and the
same database/encryption/provider configuration as the API. Sends real messages
when real providers are configured; do not run against demo/live data casually.
"""
import asyncio
import json
from sqlalchemy.exc import IntegrityError
from app.core.config import get_settings
from app.db.session import SessionLocal, init_db
from app.db.models.action import Action
from app.db.models.risk_flag import RiskFlag
from app.db.models.notification import Notification
from app.agents.agent5_escalation import check_and_escalate, _supervisor_for
from app.services.notifications import deliver_due

async def run_once(db, settings):
    check_and_escalate(db)
    actions = db.query(Action).filter(Action.type == "escalation_alert", Action.status == "pending").limit(100).all()
    for action in actions:
        if db.get(Notification, action.action_id):
            continue
        flag = db.query(RiskFlag).filter(RiskFlag.visit_id == action.visit_id, RiskFlag.actioned_at.is_(None)).first()
        supervisor = _supervisor_for(db, flag) if flag else None
        if supervisor is None or not supervisor.phone:
            continue  # Keep visible and retry configuration lookup on the next tick.
        if settings.sms_provider.lower() != "real":
            continue  # Mock delivery must not consume real supervisor alerts.
        # Supervisor alerts use SMS. Do not send free-form Meta WhatsApp outside
        # a service window or silently claim a mock notification reached a person.
        data = {"channel": "sms", "provider": settings.sms_provider,
                "phone": supervisor.phone, "text": action.content}
        db.add(Notification(action_id=action.action_id, payload_json=json.dumps(data), approved_by="system:escalation"))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # Another scheduler already enqueued this action.
    return await deliver_due(db, settings)

if __name__ == "__main__":
    init_db()
    with SessionLocal() as db:
        asyncio.run(run_once(db, get_settings()))
