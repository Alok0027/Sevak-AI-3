"""POST /api/v1/visits/transcribe (FR-01.4: transcribe-only, for review
before processing) and POST /api/v1/visits/voice (the core end-to-end
pipeline endpoint)."""
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import DbSession, require_roles
from app.core.config import get_settings
from app.schemas.visit import TranscribeRequest, TranscribeResponse, VoiceVisitRequest, VoiceVisitResponse
from app.services.bhashini_client import get_bhashini_client
from app.services.visit_pipeline import run_voice_visit

router = APIRouter(prefix="/api/v1/visits", tags=["visits"])


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_only(
    payload: TranscribeRequest,
    _user=Depends(require_roles("asha")),
) -> TranscribeResponse:
    """FR-01.4: transcribe a recording without running the rest of the
    pipeline, so the ASHA can see and correct what was heard before it
    feeds risk scoring, referral drafting, etc. Writes nothing to the DB --
    confirm via POST /visits/voice with confirmed_transcript set."""
    settings = get_settings()
    stt_client = get_bhashini_client(settings)
    transcript = await stt_client.transcribe(payload.audio_base64, payload.language_code)
    return TranscribeResponse(transcript=transcript)


@router.post("/voice", response_model=VoiceVisitResponse)
async def record_voice_visit(
    payload: VoiceVisitRequest,
    db: DbSession,
    _user=Depends(require_roles("asha")),
) -> VoiceVisitResponse:
    settings = get_settings()
    try:
        return await run_voice_visit(
            db=db,
            settings=settings,
            worker_id=payload.worker_id,
            patient_id=payload.patient_id,
            audio_base64=payload.audio_base64,
            language_code=payload.language_code,
            confirmed_transcript=payload.confirmed_transcript,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
