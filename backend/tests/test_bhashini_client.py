"""Covers the real two-step Bhashini ULCA flow (Pipeline Config Call, then
Pipeline Compute Call) added to BhashiniClient.transcribe(). Uses httpx's
built-in MockTransport (no new dependency) so this runs with no real network
access -- it verifies the request shape (headers, URLs) and response parsing
against a fixture mirroring the real API's actual response shape (confirmed
against bhashini.gitbook.io/bhashini-apis and a live getModelsPipeline call
during development), which the mock/fake-client tests elsewhere in this
suite can't catch since they never exercise real JSON parsing.
"""
import asyncio
import base64
import io
import math
import struct
import wave

import httpx
import pytest

from app.core.config import Settings
from app.services.bhashini_client import (
    BhashiniClient,
    get_bhashini_client,
    to_wav_16k_mono,
)


def _tone_wav(seconds: float = 0.5, framerate: int = 44100, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(framerate)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / framerate))) * channels
            for i in range(int(framerate * seconds))
        )
        w.writeframes(frames)
    return buf.getvalue()


def _aac_m4a(seconds: float = 0.5) -> bytes:
    """Real AAC in an MP4 container -- byte-for-byte the shape mobile sends."""
    av = pytest.importorskip("av")
    source_wav = _tone_wav(seconds)
    out = io.BytesIO()
    with av.open(io.BytesIO(source_wav)) as src, av.open(out, "w", format="mp4") as dst:
        stream = dst.add_stream("aac", rate=44100)
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=44100)
        for frame in src.decode(audio=0):
            for resampled in resampler.resample(frame):
                resampled.pts = None
                dst.mux(stream.encode(resampled))
        dst.mux(stream.encode(None))
    return out.getvalue()


def test_m4a_from_mobile_is_converted_to_the_wav_we_promise_bhashini():
    """The compute call declares audioFormat=wav/16000Hz. Mobile actually
    sends AAC in an MP4 container, and handing that over as "wav" is what
    made Bhashini's decoder return a bare 500."""
    raw = _aac_m4a()
    assert raw[4:8] == b"ftyp", "fixture should be an MP4 container, not WAV"

    converted = to_wav_16k_mono(raw)

    with wave.open(io.BytesIO(converted)) as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() > 0


def test_wav_at_the_wrong_rate_is_resampled():
    converted = to_wav_16k_mono(_tone_wav(seconds=0.5, framerate=44100, channels=2))
    with wave.open(io.BytesIO(converted)) as w:
        assert (w.getframerate(), w.getnchannels()) == (16000, 1)


def test_undecodable_audio_says_what_it_got():
    with pytest.raises(RuntimeError, match="Could not decode the submitted audio"):
        to_wav_16k_mono(b"this is not audio at all")


def _settings(**overrides) -> Settings:
    defaults = dict(
        bhashini_user_id="app-id-123",
        bhashini_api_key="udyat-key-456",
        bhashini_pipeline_id="64392f96daac500b55c543cd",
        bhashini_base_url="https://meity-auth.ulcacontrib.org",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_transcribe_does_the_config_call_then_the_compute_call(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/getModelsPipeline"):
            assert request.headers["userID"] == "app-id-123"
            assert request.headers["ulcaApiKey"] == "udyat-key-456"
            return httpx.Response(
                200,
                json={
                    "pipelineResponseConfig": [
                        {
                            "taskType": "asr",
                            "config": [{"serviceId": "ai4bharat/conformer-hi-gpu"}],
                        }
                    ],
                    "pipelineInferenceAPIEndPoint": {
                        "callbackUrl": "https://dhruva-api.bhashini.gov.in/services/inference/pipeline",
                        "inferenceApiKey": {"name": "Authorization", "value": "tok-789"},
                    },
                },
            )
        # Step 2: the compute call must hit the callbackUrl from step 1,
        # authenticated with the inferenceApiKey step 1 returned -- not the
        # static ulcaApiKey used for step 1.
        assert str(request.url) == "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"
        assert request.headers["Authorization"] == "tok-789"
        # inputData.input is required by the real API even for a pure ASR
        # task -- omitting it doesn't 400, it crashes the model service with
        # a bare 500 (this is the exact bug that was hitting production).
        import json as _json

        body = _json.loads(request.content)
        assert body["inputData"]["input"] == [{"source": ""}]
        # Whatever the caller handed us, what leaves here must match the
        # audioFormat/samplingRate this same request declares.
        sent = base64.b64decode(body["inputData"]["audio"][0]["audioContent"])
        with wave.open(io.BytesIO(sent)) as w:
            assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        assert body["pipelineTasks"][0]["config"]["audioFormat"] == "wav"
        assert body["pipelineTasks"][0]["config"]["samplingRate"] == 16000
        return httpx.Response(
            200, json={"pipelineResponse": [{"output": [{"source": "मरीज ठीक है"}]}]}
        )

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("app.services.bhashini_client.httpx.AsyncClient", fake_async_client)

    # Hand it AAC-in-MP4, exactly as mobile does, not a convenient WAV.
    mobile_audio = base64.b64encode(_aac_m4a()).decode()
    result = asyncio.run(BhashiniClient(_settings()).transcribe(mobile_audio, "hi"))

    assert result == "मरीज ठीक है"
    assert len(calls) == 2


def test_get_bhashini_client_selects_bhashini_provider():
    client = get_bhashini_client(_settings(stt_provider="bhashini"))
    assert isinstance(client, BhashiniClient)
