"""Measure how long a visit actually takes, stage by stage.

NFR-P1 says "<30s end-to-end" and NFR-P2 says "<5s for a 60s clip".
Those are targets written in a document. This produces the numbers.

    source .venv/bin/activate
    python -m scripts.measure_latency --runs 30 --audio clip.m4a

Reports p50 and p95 rather than a mean, because a mean hides the slow
tail and the slow tail is what an ASHA standing in a doorway actually
experiences.

No database. The agent graph reads its inputs from the state dict and
writes nothing -- persistence happens in visit_pipeline.run_voice_visit,
one layer up, which this deliberately does not call: timing an INSERT
into a local SQLite file tells you nothing about a pipeline whose time
goes to a speech API and a language model. An earlier version of this
script built a scratch database, seeded a worker and a patient, and
generated an encryption key to do it. None of it was ever read, and both
times this script failed before producing a number, it failed in that
setup rather than in anything being measured.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agents.graph import build_pipeline_graph  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.services.bhashini_client import get_bhashini_client  # noqa: E402
from app.services.llm_client import get_llm_client  # noqa: E402
from app.services.sms_client import get_sms_client  # noqa: E402
from app.services.whatsapp_client import get_whatsapp_client  # noqa: E402

# Used only when the mock STT is active -- it is the one provider for
# which a text payload *is* the audio, because it decodes this straight
# back.
SAMPLE_HI = (
    "सुनीता देवी, बत्तीस साल, सात महीने की गर्भवती। "
    "बीपी एक सौ साठ बटा सौ, सिर में तेज़ दर्द और पैरों में सूजन है।"
)

STAGES = [
    "transcribe",
    "agent1_voice_comprehension",
    "agent2_risk_classification",
    "agent3_action_generation",
    "agent4_reporting",
]


def pct(values: list[float], p: float) -> float:
    """Nearest-rank percentile. Deliberately not statistics.quantiles():
    that interpolates, and with 30 samples an interpolated p95 reports a
    number that was never observed."""
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(p / 100 * len(ordered) + 0.5) - 1))
    return ordered[k]


async def one_run(graph, audio_b64: str) -> dict[str, float]:
    state = {
        "worker_id": "bench-worker",
        "patient_id": "bench-patient",
        "patient_name": "Benchmark Patient",
        "patient_phone": "9000000002",
        "audio_base64": audio_b64,
        "language_code": "hi",
    }
    timings: dict[str, float] = {}
    # astream yields after each node, so the gap between yields is that
    # node's wall time -- no instrumentation in the request path.
    started = last = time.perf_counter()
    async for chunk in graph.astream(state):
        now = time.perf_counter()
        for node in chunk:
            timings[node] = (now - last) * 1000
        last = now
    timings["TOTAL"] = (time.perf_counter() - started) * 1000
    return timings


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--audio", help=(
        "Path to a real recording (wav/m4a/mp3/ogg). Required when "
        "stt_provider is a real one. NFR-P2 is written about a 60s clip, "
        "so use one of about that length."))
    args = ap.parse_args()
    settings = get_settings()

    # The default payload is base64 of Hindi *text*. A real provider is
    # handed it as audio, cannot decode it, and throws -- and a timing
    # taken from a failed request is not a latency, it is the speed of an
    # error.
    if settings.stt_provider != "mock" and not args.audio:
        print(f"stt_provider={settings.stt_provider} needs a real recording.\n")
        print("  python -m scripts.measure_latency --runs 30 --audio path/to/clip.m4a\n")
        print("Use a clip of roughly 60 seconds: NFR-P2 is written about a 60s")
        print("clip, and a 3-second one would answer a different question.")
        return 2

    raw = open(args.audio, "rb").read() if args.audio else b""
    audio_b64 = base64.b64encode(raw or SAMPLE_HI.encode()).decode()

    graph = build_pipeline_graph(
        get_bhashini_client(settings),
        get_llm_client(settings),
        get_whatsapp_client(settings),
        get_sms_client(settings),
    )

    print(f"SevakAI pipeline latency — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    print(f"runs={args.runs}  stt_provider={settings.stt_provider}  "
          f"llm_provider={settings.llm_provider}  use_mocks={settings.use_mocks}")
    print(f"audio={args.audio or 'synthetic text payload (mock STT only)'}"
          f"{f' ({len(raw) / 1024:.0f} KB)' if raw else ''}")
    print()

    # One untimed pass: the first call pays for model construction and
    # connection setup, and reporting that as the typical case would be
    # dishonest in the other direction.
    await one_run(graph, audio_b64)

    samples: dict[str, list[float]] = {}
    for i in range(args.runs):
        for node, ms in (await one_run(graph, audio_b64)).items():
            samples.setdefault(node, []).append(ms)
        print(f"\r  run {i + 1}/{args.runs}", end="", flush=True, file=sys.stderr)
    print("\r" + " " * 24 + "\r", end="", file=sys.stderr)

    print(f"{'stage':<32}{'p50':>9}{'p95':>9}{'min':>9}{'max':>9}")
    print("-" * 68)
    for node in STAGES + ["TOTAL"]:
        if v := samples.get(node):
            label = node if node != "TOTAL" else "TOTAL (excl. network + DB write)"
            print(f"{label:<32}{pct(v, 50):>8.1f}ms{pct(v, 95):>8.1f}ms"
                  f"{min(v):>8.1f}ms{max(v):>8.1f}ms")
    print()

    # STT and the LLM are what the clock is measuring. If either is mocked
    # the total is the speed of a base64 decode and a canned string, and
    # no verdict is issued -- an earlier version cheerfully printed
    # "p95 = 0.00s (PASS)" on exactly that.
    #
    # use_mocks is reported but does not block: it gates WhatsApp and SMS,
    # which are independent of stt_provider and llm_provider. It does
    # touch agent3, which sends the message, so it is named in the caveat.
    blocking = [f"{n}={v}" for n, v in (("stt_provider", settings.stt_provider),
                                        ("llm_provider", settings.llm_provider))
                if v == "mock"]
    if blocking:
        print("NO VERDICT — the providers that dominate the time are mocked:")
        for m in blocking:
            print(f"      {m}")
        print("\n      These figures are the speed of a base64 decode and canned")
        print("      strings, not of speech recognition and a language model.")
        print("      They must not be quoted as SevakAI's latency.")
        return 2

    total_p95 = pct(samples["TOTAL"], 95)
    print(f"NFR-P1 target <30s end-to-end: p95 = {total_p95 / 1000:.2f}s "
          f"({'PASS' if total_p95 < 30000 else 'FAIL'})")
    if settings.use_mocks:
        print("\n      CAVEAT: use_mocks=true, so WhatsApp and SMS are mocked.")
        print("      Speech recognition and the language model above are real,")
        print("      but agent3 sends the message, so its row excludes real")
        print("      delivery time. Re-run with USE_MOCKS=false for the live figure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
