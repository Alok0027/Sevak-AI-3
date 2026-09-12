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
  - BhashiniClient ("bhashini"): real ULCA pipeline call, as a genuine
    two-step flow (confirmed working against the live API):
      1. POST {base_url}/ulca/apis/v0/model/getModelsPipeline with
         userID/ulcaApiKey headers -- returns the assigned ASR serviceId
         plus a per-call inferenceApiKey + callbackUrl.
      2. POST that callbackUrl with the returned inferenceApiKey as the
         Authorization header -- returns the actual transcript.
    Fill in BHASHINI_* env vars and set STT_PROVIDER=bhashini to switch
    over -- no other file needs to change, since all three implement
    transcribe(). BHASHINI_USER_ID is the Bhashini application ID (not a
    personal user id); BHASHINI_API_KEY is the "Udyat Key" shown on the
    Bhashini dashboard's API Keys page; BHASHINI_PIPELINE_ID is one of the
    two standard published pipeline ids (MeitY's or AI4Bharat's), not
    something per-account -- see bhashini.gitbook.io/bhashini-apis.

Real API reference: bhashini.gitbook.io/bhashini-apis (Pipeline Config Call, Pipeline Compute Call)
"""
import asyncio
import base64
import io
import os
import tempfile
import wave
from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings


def to_wav_16k_mono(raw: bytes) -> bytes:
    """Decode any audio container we're given and re-encode it as 16kHz mono
    16-bit PCM WAV.

    The compute call below *tells* Bhashini the audio is "wav" at 16000Hz, so
    this makes that true rather than trusting the caller. Mobile records AAC
    in an MP4 container (the record plugin falls back to the platform
    recorder on Android regardless of the encoder we ask for), and handing
    that to Bhashini as "wav" crashes their decoder with a bare 500 -- the
    exact failure this fixes. Keeping the phone on compressed audio is also
    the right call for an ASHA on a rural connection: the same clip is ~10x
    smaller to upload than raw WAV, and this converts it after it lands.

    PyAV is already a dependency (via faster-whisper) and bundles its own
    ffmpeg, so this needs no system binary.
    """
    import av  # imported lazily: only the real Bhashini path needs it

    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    chunks = []
    try:
        with av.open(io.BytesIO(raw)) as container:
            for frame in container.decode(audio=0):
                for resampled in resampler.resample(frame):
                    chunks.append(resampled.to_ndarray().tobytes())
        for resampled in resampler.resample(None):  # flush
            chunks.append(resampled.to_ndarray().tobytes())
    except Exception as exc:
        raise RuntimeError(
            f"Could not decode the submitted audio ({len(raw)} bytes starting "
            f"{raw[:12]!r}): {exc}"
        ) from exc

    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"".join(chunks))
    return buf.getvalue()


def describe_audio(audio_base64: str) -> str:
    """Summarise what we actually sent, for an ASR failure message.

    A rejected ASR call is nearly always about the audio, and the useful
    question is whether what we sent matches what we *told* the API it was
    ("wav", 16kHz, mono). "16000Hz, 1ch, 16-bit, 3.2s" vs "not a RIFF/WAVE
    file at all" points straight at the cause; the raw status code doesn't.
    """
    try:
        raw = base64.b64decode(audio_base64)
    except Exception:
        return "audio that isn't valid base64"
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        return f"{len(raw)} bytes starting {raw[:12]!r} -- not a RIFF/WAVE file"
    try:
        with wave.open(io.BytesIO(raw)) as w:
            framerate = w.getframerate()
            seconds = w.getnframes() / framerate if framerate else 0
            return (
                f"{len(raw)} bytes of WAV: {framerate}Hz, {w.getnchannels()}ch, "
                f"{w.getsampwidth() * 8}-bit, {seconds:.1f}s"
            )
    except Exception as exc:
        return f"{len(raw)} bytes of WAV with an unreadable header ({exc})"


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
    """Real Bhashini ULCA pipeline client -- genuine two-step flow (Pipeline
    Config Call, then Pipeline Compute Call), confirmed against the live API
    with real credentials during development. No fallback to the mock on
    failure (matches WhatsAppClient/TwilioSmsClient -- a real external-call
    failure here should surface, not be silently swallowed)."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def transcribe(self, audio_base64: str, language_code: str) -> str:
        # Normalise to the format we're about to claim this audio is, before
        # claiming it. Decoding is CPU-bound, so keep it off the event loop.
        wav = await asyncio.to_thread(to_wav_16k_mono, base64.b64decode(audio_base64))
        audio_base64 = base64.b64encode(wav).decode()

        headers = {
            "userID": self.settings.bhashini_user_id,
            "ulcaApiKey": self.settings.bhashini_api_key,
            "Content-Type": "application/json",
        }
        config_payload = {
            "pipelineTasks": [
                {"taskType": "asr", "config": {"language": {"sourceLanguage": language_code}}}
            ],
            "pipelineRequestConfig": {"pipelineId": self.settings.bhashini_pipeline_id},
        }
        async with httpx.AsyncClient(timeout=15) as client:
            # Step 1: Pipeline Config Call -- tells us which ASR serviceId
            # we've been assigned for this language, plus a per-call
            # inferenceApiKey + callbackUrl for step 2. This is NOT the
            # same as the static "Inference" key shown on the Bhashini
            # dashboard -- that dashboard value is a separate credential;
            # the real per-request token always comes from this response.
            config_resp = await client.post(
                f"{self.settings.bhashini_base_url}/ulca/apis/v0/model/getModelsPipeline",
                headers=headers,
                json=config_payload,
            )
            config_resp.raise_for_status()
            config_data = config_resp.json()

            asr_config = config_data["pipelineResponseConfig"][0]["config"][0]
            service_id = asr_config["serviceId"]
            endpoint = config_data["pipelineInferenceAPIEndPoint"]
            callback_url = endpoint["callbackUrl"]
            inference_key = endpoint["inferenceApiKey"]

            # Step 2: Pipeline Compute Call -- the actual ASR inference,
            # authenticated with the token we just got back above.
            compute_payload = {
                "pipelineTasks": [
                    {
                        "taskType": "asr",
                        "config": {
                            "language": {"sourceLanguage": language_code},
                            "serviceId": service_id,
                            "audioFormat": "wav",
                            "samplingRate": 16000,
                        },
                    }
                ],
                # inputData.input is required by the real API even for a
                # pure ASR task (confirmed against bhashini.gitbook.io's
                # Pipeline Compute Call request-payload example) -- omitting
                # it entirely doesn't get a clean 400, it crashes the model
                # service with a bare "Internal Server Error" (no JSON body).
                # The doc example shows "source": null, but the live API
                # actually 422s on that ("none is not an allowed value") --
                # it wants a string, so an empty one is what the docs meant.
                "inputData": {
                    "input": [{"source": ""}],
                    "audio": [{"audioContent": audio_base64}],
                },
            }
            compute_resp = await client.post(
                callback_url,
                headers={
                    inference_key["name"]: inference_key["value"],
                    "Content-Type": "application/json",
                },
                json=compute_payload,
            )
            if compute_resp.status_code >= 400:
                # raise_for_status() alone drops the response body, which is
                # exactly where Bhashini explains *why* (bad audio format,
                # unsupported serviceId, etc) -- surface it so a real failure
                # is debuggable from the backend log alone.
                raise RuntimeError(
                    f"Bhashini inference call failed ({compute_resp.status_code}): "
                    f"{compute_resp.text[:500]} "
                    f"[serviceId={service_id}, sent {describe_audio(audio_base64)}]"
                )
            compute_data = compute_resp.json()
            return compute_data["pipelineResponse"][0]["output"][0]["source"]


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
