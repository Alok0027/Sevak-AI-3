"""Hit the real Bhashini ULCA API directly, outside the app, to find out why
an ASR call is failing.

The app's own failures only tell us "the compute call returned 500". This
answers the question that actually matters: does Bhashini accept a *known
good* audio file? It synthesises a clean 16kHz mono 16-bit PCM WAV locally,
so nothing about the phone, the recorder plugin or the network path is in
play -- if that clean file also fails, the problem is our request (or the
account/pipeline); if it succeeds, the problem is the audio the phone sends.

It then re-runs the same call across a few payload variants, because the
published docs and the live API disagree in places (the docs show
inputData.input[0].source as null; the live API 422s on null).

Credentials come from .env via the app's own Settings, exactly like the
running server -- nothing is printed except the API key's length.

    cd backend
    source .venv/bin/activate
    python3 scripts/bhashini_smoke_test.py            # synthetic tone
    python3 scripts/bhashini_smoke_test.py some.wav   # a real recording
"""
import asyncio
import base64
import io
import math
import struct
import sys
import wave

import httpx

sys.path.insert(0, ".")

from app.core.config import get_settings  # noqa: E402
from app.services.bhashini_client import describe_audio  # noqa: E402


def synthetic_wav(seconds: int = 2, framerate: int = 16000) -> bytes:
    """A clean 16kHz mono 16-bit PCM WAV -- a 440Hz tone.

    Not speech, so a working ASR will return an empty/garbage transcript --
    that's fine and expected. We're testing whether the service *accepts and
    decodes* the audio, not whether it hears words.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(
            b"".join(
                struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / framerate)))
                for i in range(framerate * seconds)
            )
        )
    return buf.getvalue()


async def main() -> None:
    settings = get_settings()
    print("--- credentials (values never printed) ---")
    print(f"  BHASHINI_USER_ID    : {len(settings.bhashini_user_id)} chars")
    print(f"  BHASHINI_API_KEY    : {len(settings.bhashini_api_key)} chars")
    print(f"  BHASHINI_PIPELINE_ID: {settings.bhashini_pipeline_id}")
    print(f"  BHASHINI_BASE_URL   : {settings.bhashini_base_url}")
    print(f"  STT_PROVIDER        : {settings.stt_provider}")

    if len(sys.argv) > 1:
        audio = open(sys.argv[1], "rb").read()
        print(f"\nUsing audio file {sys.argv[1]}")
    else:
        audio = synthetic_wav()
        print("\nUsing a synthetic 440Hz tone (known-good 16kHz mono PCM WAV)")
    audio_b64 = base64.b64encode(audio).decode()
    print(f"  -> {describe_audio(audio_b64)}")

    async with httpx.AsyncClient(timeout=60) as client:
        print("\n--- step 1: pipeline config call ---")
        config_resp = await client.post(
            f"{settings.bhashini_base_url}/ulca/apis/v0/model/getModelsPipeline",
            headers={
                "userID": settings.bhashini_user_id,
                "ulcaApiKey": settings.bhashini_api_key,
                "Content-Type": "application/json",
            },
            json={
                "pipelineTasks": [
                    {"taskType": "asr", "config": {"language": {"sourceLanguage": "hi"}}}
                ],
                "pipelineRequestConfig": {"pipelineId": settings.bhashini_pipeline_id},
            },
        )
        print(f"  status {config_resp.status_code}")
        if config_resp.status_code >= 400:
            print(f"  body: {config_resp.text[:1000]}")
            print("\nThe config call itself failed -- credentials or pipeline id.")
            return

        data = config_resp.json()
        asr_task = data["pipelineResponseConfig"][0]
        endpoint = data["pipelineInferenceAPIEndPoint"]
        callback_url = endpoint["callbackUrl"]
        inference_key = endpoint["inferenceApiKey"]
        print(f"  callbackUrl : {callback_url}")
        print(f"  auth header : {inference_key['name']} ({len(inference_key['value'])} chars)")
        print("  ASR services offered for 'hi':")
        for entry in asr_task["config"]:
            langs = entry.get("language", {})
            print(
                f"    - {entry['serviceId']}"
                f"  (source={langs.get('sourceLanguage')})"
            )
        service_id = asr_task["config"][0]["serviceId"]

        headers = {
            inference_key["name"]: inference_key["value"],
            "Content-Type": "application/json",
        }

        def payload(**config_overrides):
            config = {
                "language": {"sourceLanguage": "hi"},
                "serviceId": service_id,
                "audioFormat": "wav",
                "samplingRate": 16000,
            }
            config.update(config_overrides)
            return {
                "pipelineTasks": [{"taskType": "asr", "config": config}],
                "inputData": {
                    "input": [{"source": ""}],
                    "audio": [{"audioContent": audio_b64}],
                },
            }

        variants = [
            ("as the app sends it", payload()),
            ("without the inputData.input key", {
                "pipelineTasks": [payload()["pipelineTasks"][0]],
                "inputData": {"audio": [{"audioContent": audio_b64}]},
            }),
            ("without audioFormat/samplingRate", {
                "pipelineTasks": [
                    {
                        "taskType": "asr",
                        "config": {
                            "language": {"sourceLanguage": "hi"},
                            "serviceId": service_id,
                        },
                    }
                ],
                "inputData": {
                    "input": [{"source": ""}],
                    "audio": [{"audioContent": audio_b64}],
                },
            }),
            ("samplingRate 8000", payload(samplingRate=8000)),
            ("audioFormat pcm", payload(audioFormat="pcm")),
        ]

        print("\n--- step 2: compute call variants ---")
        for label, body in variants:
            try:
                resp = await client.post(callback_url, headers=headers, json=body)
            except Exception as exc:
                print(f"  [{label}] raised {type(exc).__name__}: {exc}")
                continue
            snippet = resp.text[:300].replace("\n", " ")
            print(f"  [{label}] -> {resp.status_code}: {snippet}")
            if resp.status_code < 400:
                print("     ^^^ THIS ONE WORKS")

        if len(sys.argv) > 1:
            return

        # A 2s clip proves the request shape is right, but a real home-visit
        # note is 20-60s -- an order of magnitude more base64 in the body.
        # If there's a size ceiling, that's where a valid request starts
        # failing, and the app has to chunk or downsample rather than send
        # the whole recording in one POST.
        print("\n--- step 3: how long a clip does it accept? ---")
        for seconds in (5, 15, 30, 60):
            long_b64 = base64.b64encode(synthetic_wav(seconds)).decode()
            body = {
                "pipelineTasks": [
                    {
                        "taskType": "asr",
                        "config": {
                            "language": {"sourceLanguage": "hi"},
                            "serviceId": service_id,
                            "audioFormat": "wav",
                            "samplingRate": 16000,
                        },
                    }
                ],
                "inputData": {
                    "input": [{"source": ""}],
                    "audio": [{"audioContent": long_b64}],
                },
            }
            size = f"{seconds:>2}s, {len(long_b64) // 1024}KB base64"
            try:
                resp = await client.post(callback_url, headers=headers, json=body)
            except Exception as exc:
                print(f"  [{size}] raised {type(exc).__name__}: {exc}")
                continue
            print(f"  [{size}] -> {resp.status_code}: {resp.text[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
