"""POST /api/v1/sync/batch (FR-01.3, FR-07.1: offline queue flush).

Each queued "visit" record (recorded offline, with its audio still attached)
is run through the exact same pipeline as a live POST /visits/voice call --
that's what FR-01.3's acceptance criterion ("syncs and transcribes within
30 seconds of connectivity") actually requires, not just a queue write.
Any other record_type is logged to sync_queue for now (extend here as the
mobile app grows more offline-capable record types)."""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_roles
from app.core.config import get_settings
from app.db.models.sync_queue import SyncQueueEntry
from app.schemas.sync import SyncBatchRequest, SyncBatchResponse
from app.services.visit_pipeline import run_voice_visit

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


@router.post("/batch", response_model=SyncBatchResponse)
async def sync_batch(
    payload: SyncBatchRequest,
    db: DbSession,
    _user=Depends(require_roles("asha")),
) -> SyncBatchResponse:
    settings = get_settings()
    synced = 0
    errors: list[str] = []

    for record in payload.records:
        record_type = record.get("record_type", "visit")
        entry = SyncQueueEntry(
            worker_id=payload.worker_id,
            record_type=record_type,
            record_json=json.dumps(record),
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)

        try:
            if record_type == "visit" and record.get("audio_base64"):
                await run_voice_visit(
                    db=db,
                    settings=settings,
                    worker_id=payload.worker_id,
                    patient_id=record["patient_id"],
                    audio_base64=record["audio_base64"],
                    language_code=record.get("language_code", "hi"),
                )
            entry.synced_at = datetime.now(timezone.utc)
            db.commit()
            synced += 1
        except Exception as exc:  # noqa: BLE001 -- report and continue, don't fail the whole batch
            entry.retry_count += 1
            db.commit()
            errors.append(f"{record_type} for patient {record.get('patient_id')}: {exc}")

    return SyncBatchResponse(synced=synced, failed=len(errors), errors=errors)
