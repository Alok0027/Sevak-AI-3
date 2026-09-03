"""
Speech-to-text (FR-01.2, NFR-P2: <5s for a 60s clip).

Three implementations behind one interface, selected by STT_PROVIDER:
  - MockBhashiniClient ("mock", the default): decodes the base64 payload as
    UTF-8 text and returns it directly. For the demo/dev dataset we
    base64-encode the *known* transcript as the "audio" payload, so the mock
    behaves deterministically end-to-end without ever calling the network.
  - WhisperSttClient ("whisper"): real speech recognition via a locally
    hosted Whisper model (faster-whisper). No API key, no network call once
    the model weights are cached -- this is the stand-in while Bhashini
    access is pending, so we can demo genuine voice recognition (e.g. to a
    capstone mentor) without waiting on API approval.
  - BhashiniClient ("bhashini"): real ULCA pipeline call. Fill in
    BHASHINI_* env vars and set STT_PROVIDER=bhashini to switch over --
    no other file needs to change, since all three implement transcribe().

Real API reference: bhashini.gov.in/ulca -> POST {base_url}/ulca/apis/v0/model/pipeline
"""
import asyncio
import base64
import os
import tempfile
from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings


class BhashiniClientBase(ABC):
    @abstractmethod
    async def transcribe(self, audio_base64: str, language_code: str) -> str:
        """Return transcribed text for a base64-encoded audio clip."""


class MockBhashiniClient(BhashiniClientBase):
    async def transcribe(self, audio_base64: str, language_code: str) -> str:
        try:
            return base64.b64decode(audio_base64).decode("utf-8")
        except Exception:
            # Not decodable text (e.g. a real audio blob was passed against
            # the mock client) -- return a generic placeholder so the
            # pipeline still runs end-to-end for smoke-testing.
            return "[mock transcription unavailable for binary audio input]"


class BhashiniClient(BhashiniClientBase):
    """Real Bhashini ULCA pipeline client. TODO before going live:
    1. Register at bhashini.gov.in/ulca, get BHASHINI_API_KEY / USER_ID / PIPELINE_ID.
    2. Confirm the pipeline config below matches the ASR model you were assigned.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    async def transcribe(self, audio_base64: str, language_code: str) -> str:
        headers = {
            "userID": self.settings.bhashini_user_id,
            "ulcaApiKey": self.settings.bhashini_api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "pipelineTasks": [
                {
                    "taskType": "asr",
                    "config": {
                        "language": {"sourceLanguage": language_code},
                        "serviceId": self.settings.bhashini_pipeline_id,
                        "audioFormat": "wav",
                        "samplingRate": 16000,
                    },
                }
            ],
            "inputData": {"audio": [{"audioContent": audio_base64}]},
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.settings.bhashini_base_url}/ulca/apis/v0/model/pipeline",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            # NOTE: exact response shape depends on the assigned ASR service --
            # adjust this parse once real credentials are available.
            return data["pipelineResponse"][0]["output"][0]["source"]


class WhisperSttClient(BhashiniClientBase):
    """Local, self-hosted ASR via faster-whisper -- a real-recognition
    stand-in for Bhashini's ASR endpoint while API access is pending.

    Runs on-device (CPU, int8), so there's no API key and no per-request
    network call once the model weights are cached locally (first use
    downloads them from Hugging Face, a few hundred MB depending on
    WHISPER_MODEL_SIZE). Mobile records .m4a; faster-whisper decodes audio
    via PyAV, so no separate ffmpeg conversion step is needed here.

    Mobile already sends ISO language codes (hi, mr, ta, te, bn) that match
    Whisper's own language codes directly, so `language_code` is passed
    straight through as a hint rather than translated.
    """

    _model = None  # loaded lazily once per process, shared across requests

    def __init__(self, settings: Settings):
        self.settings = settings

    def _get_model(self):
        if WhisperSttClient._model is None:
            from faster_whisper import WhisperModel

            WhisperSttClient._model = WhisperModel(
                self.settings.whisper_model_size, device="cpu", compute_type="int8"
            )
        return WhisperSttClient._model

    async def transcribe(self, audio_base64: str, language_code: str) -> str:
        return await asyncio.to_thread(self._transcribe_sync, audio_base64, language_code)

    def _transcribe_sync(self, audio_base64: str, language_code: str) -> str:
        audio_bytes = base64.b64decode(audio_base64)
        fd, tmp_path = tempfile.mkstemp(suffix=".m4a")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(audio_bytes)
            model = self._get_model()
            segments, _info = model.transcribe(
                tmp_path, language=language_code or None, vad_filter=True
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text or "[no speech detected]"
        finally:
            os.unlink(tmp_path)


def get_bhashini_client(settings: Settings) -> BhashiniClientBase:
    provider = settings.stt_provider.lower()
    if provider == "whisper":
        return WhisperSttClient(settings)
    if provider == "bhashini":
        return BhashiniClient(settings)
    return MockBhashiniClient()
