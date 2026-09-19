"""Durable, bounded delivery. Unknown outcomes must be reconciled, not resent."""
import json
import hashlib
from datetime import datetime, timedelta, timezone
import httpx
from fastapi import HTTPException
from app.db.models.notification import Notification
from app.db.models.action import Action
from app.agents.agent3_action_generation import FOLLOWUP_DAYS, _RISK_WORD, _WHEN_WORD
from app.services.sms_client import get_sms_client
from app.services.whatsapp_client import get_whatsapp_client


def preview(action, visit, patient, channel, settings):
    if not patient.phone:
        raise HTTPException(422, "Patient has no phone number")
    payload = {"channel": channel, "phone": patient.phone, "text": action.content}
    effective_wa = settings.whatsapp_provider.lower()
    if effective_wa == "mock" and not settings.use_mocks:
        effective_wa = "meta"
    if channel == "whatsapp" and effective_wa == "meta":
        if settings.whatsapp_template_name != "followup_reminder" or settings.whatsapp_template_language != "hi":
            raise HTTPException(409, "Configure a verified preview for this WhatsApp template before approval")
        days = FOLLOWUP_DAYS.get(visit.risk_level, 30)
        params = [patient.name, _RISK_WORD.get(visit.risk_level, visit.risk_level), _WHEN_WORD.get(days, f"{days} दिन में")]
        payload.update(template=settings.whatsapp_template_name, language="hi", params=params,
            text=f"नमस्ते {params[0]} जी। आपकी हाल की जाँच में {params[1]} पाया गया है। कृपया {params[2]} अपनी आशा कार्यकर्ता से मिलें।")
    payload["provider"] = effective_wa if channel == "whatsapp" else settings.sms_provider
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload, digest


async def deliver_due(db, settings, limit=50):
    now = datetime.now(timezone.utc)
    # A worker that died after claiming a send must never be blindly restarted.
    stale = db.query(Notification).filter(Notification.status == "sending",
        Notification.next_attempt_at <= now).limit(limit).all()
    for item in stale:
        item.status = "needs_review"
        item.last_error = "Worker stopped during delivery; reconcile with provider"
        db.get(Action, item.action_id).status = "needs_review"
    db.commit()
    ids = [row[0] for row in db.query(Notification.action_id).filter(
        Notification.status.in_(["queued", "retry"]), Notification.next_attempt_at <= now,
        Notification.attempts < 5).order_by(Notification.next_attempt_at).limit(limit).all()]
    count = 0
    for action_id in ids:
        claimed = db.query(Notification).filter(Notification.action_id == action_id,
            Notification.status.in_(["queued", "retry"]), Notification.next_attempt_at <= now,
            Notification.attempts < 5).update({
                Notification.status: "sending", Notification.attempts: Notification.attempts + 1,
                Notification.next_attempt_at: now + timedelta(minutes=15)}, synchronize_session=False)
        db.commit()  # Claim before provider I/O; competing workers cannot send it.
        if not claimed:
            continue
        item = db.get(Notification, action_id)
        db.refresh(item)
        action = db.get(Action, action_id)
        data = json.loads(item.payload_json)
        try:
            provider = settings.whatsapp_provider if data["channel"] == "whatsapp" else settings.sms_provider
            if data["channel"] == "whatsapp" and provider == "mock" and not settings.use_mocks:
                provider = "meta"
            if data.get("provider") != provider:
                item.status = "blocked"
                item.last_error = "Provider changed after approval"
                action.status = "blocked"
                db.commit()
                continue
            client = get_whatsapp_client(settings) if data["channel"] == "whatsapp" else get_sms_client(settings)
            if data.get("template"):
                result = await client.send_template(data["phone"], data["template"], data["params"], data["language"])
            else:
                result = await client.send_message(data["phone"], data["text"])
            item.status = "mock_sent" if result.get("status") == "mock_sent" else "accepted"
            item.provider_id = result.get("sid") or next((m.get("id") for m in result.get("messages", []) if m.get("id")), None)
            item.last_error = None
            action.status = item.status
            action.sent_at = datetime.now(timezone.utc)
            count += 1
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            # No request was sent. These failures are safe to retry automatically.
            item.status = "retry" if item.attempts < 5 else "failed"
            item.last_error = type(exc).__name__
            item.next_attempt_at = now + timedelta(minutes=2 ** item.attempts)
            action.status = item.status
        except Exception as exc:
            # A read timeout/process crash may follow provider acceptance.
            # At-most-once automatic dispatch is safer than duplicate health texts.
            item.status = "needs_review"
            item.last_error = type(exc).__name__
            action.status = item.status
        db.commit()
    return count
