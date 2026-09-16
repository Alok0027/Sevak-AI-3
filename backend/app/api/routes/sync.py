"""POST /api/v1/sync/batch (FR-01.3, FR-07.1: offline queue flush).

Each queued "visit" record (recorded offline, with its audio still attached)
is run through the exact same pipeline as a live POST /visits/voice call --
that's what FR-01.3's acceptance criterion ("syncs and transcribes within
30 seconds of connectivity") actually requires, not just a queue write.
Two record types are processed: "patient" and "visit". Anything else is
logged to sync_queue and left for a later release.

Patients are applied before visits regardless of the order they arrive in.
A visit recorded offline for a patient registered offline references a
patient_id the server has never seen, so the reverse order fails the visit
and then succeeds the patient -- leaving a queue that retries forever and
an ASHA whose morning did not sync. The client cannot fix this by sorting
its own queue either, because a batch can span several days of work.

That works because patient_id is a client-generatable UUID rather than a
server sequence: the phone mints the id when the ASHA taps Save with no
signal, the visit references it immediately, and sync reconciles both."""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_roles
from app.core.config import get_settings
from app.db.models.patient import Patient
from app.db.models.sync_queue import SyncQueueEntry
from app.db.models.worker import Worker
from app.schemas.sync import SyncBatchRequest, SyncBatchResponse
from app.services import identity
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

    # Patients first -- see the module docstring.
    ordered = sorted(
        payload.records,
        key=lambda r: 0 if r.get("record_type") == "patient" else 1,
    )

    for record in ordered:
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
            if record_type == "patient":
                _apply_patient(db, payload.worker_id, record)
            elif record_type == "visit" and record.get("audio_base64"):
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


def _apply_patient(db, worker_id: str, record: dict) -> None:
    """Create a patient the ASHA registered while offline.

    Idempotent on patient_id. A batch that half-succeeded and got retried
    -- the ordinary case on a connection that comes and goes -- must not
    produce a second copy of the same woman, because the duplicate carries
    its own visits and the two records then disagree about her history.

    The id is taken from the record when the phone supplied one, so the
    visits queued against it resolve. Falls back to a server-generated id
    only for a client old enough not to send one, whose visits could not
    have referenced it anyway.
    """
    patient_id = record.get("patient_id")
    if patient_id:
        existing = db.query(Patient).filter(Patient.patient_id == patient_id).first()
        if existing is not None:
            return

    name = (record.get("name") or "").strip()
    if not name:
        raise ValueError("patient record has no name")

    village = (record.get("village") or "").strip() or None
    phone = record.get("phone")
    # Derived exactly as POST /patients derives them, rather than left for
    # backfill_identity() to fix on the next boot. A woman registered with
    # no signal is not a second-class record: until these are set she is
    # invisible to the duplicate check and to every village lookup, so the
    # colleague who registers her again tomorrow is not warned.
    owner = db.query(Worker).filter(Worker.worker_id == worker_id).first()
    try:
        rch = identity.normalise_rch(record.get("rch_number"))
    except identity.InvalidRchNumber:
        # Typed wrong on a phone with no signal, days ago. Dropping the
        # number keeps the woman; refusing the record loses her, and she
        # is the part that cannot be re-entered from memory. The ASHA can
        # correct the number once it is on her list.
        rch = None

    # rch_number is unique. Somebody else registering the same woman while
    # this phone was offline is not a reason to fail the whole batch and
    # strand every other record in it -- keep her, drop the number, and
    # let the duplicate surface on the list where a human can merge them.
    if rch and db.query(Patient).filter(Patient.rch_number == rch).first() is not None:
        rch = None

    patient = Patient(
        worker_id=worker_id,
        name=name,
        age=record.get("age"),
        gender=record.get("gender"),
        village=village,
        village_code=identity.village_code(village),
        sub_centre_id=owner.sub_centre_id if owner else None,
        phone=phone,
        phone_hash=identity.phone_index(phone),
        rch_number=rch,
        pregnancy_stage=record.get("pregnancy_stage"),
    )
    if patient_id:
        patient.patient_id = patient_id
    db.add(patient)
    db.flush()
