"""Measure how long a visit actually takes, stage by stage.

NFR-P1 says "<30s end-to-end" and NFR-P2 says "<5s for a 60s clip".
Those are targets written in a document. This produces the numbers.

Run it:

    python -m scripts.measure_latency --runs 30

What it does NOT measure, and says so in its own output:

  * Real Bhashini or Whisper transcription time, unless you run it with
    STT_PROVIDER set to one of those. On the default mock provider the
    transcribe stage is a base64 decode and will read as ~0ms, which is
    not a speech-recognition latency and must never be quoted as one.
  * Network time to a deployed instance. That is measure_load.py's job.

Reporting p50 and p95 rather than a mean, because a mean hides the slow
tail and the slow tail is what an ASHA standing in a doorway actually
experiences.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# A scratch database, created before anything imports app.db.session (which
# reads DATABASE_URL once, at module import).
#
# The benchmark used to run against whatever dev database happened to be
# lying about. That made it unreproducible -- on one machine the rows were
# encrypted with a different key and it died on decryption rather than on
# anything to do with latency. Pipeline speed does not depend on which
# patient row it reads, so the script now builds its own two rows and any
# reviewer can re-run it on a clean checkout and get a comparable number.
_SCRATCH = os.environ.get("LATENCY_DB") or os.path.join(
    tempfile.gettempdir(), "sevakai_latency_bench.db"
)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_SCRATCH}")
# The field-encryption key must be valid urlsafe-base64 of 32 bytes. A
# throwaway one, generated per run: this database holds two invented rows
# and is deleted afterwards, and a key checked into a repo is a key
# somebody eventually uses in earnest.
os.environ.setdefault(
    "ENCRYPTION_KEY",
    __import__("base64").urlsafe_b64encode(__import__("os").urandom(32)).decode(),
)

from app.agents.graph import build_pipeline_graph  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.models.patient import Patient  # noqa: E402
from app.db.models.worker import Worker  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.services.bhashini_client import get_bhashini_client  # noqa: E402
from app.services.llm_client import get_llm_client  # noqa: E402
from app.services.sms_client import get_sms_client  # noqa: E402
from app.services.whatsapp_client import get_whatsapp_client  # noqa: E402

# A realistic HIGH-risk dictation: the path that does the most work, so
# the figures are the slow case rather than a flattering one.
SAMPLE_HI = (
    "सुनीता देवी, बत्तीस साल, सात महीने की गर्भवती। "
    "बीपी एक सौ साठ बटा सौ, सिर में तेज़ दर्द और पैरों में सूजन है। "
    "कल से खाना नहीं खा पा रही, चक्कर आ रहे हैं।"
)

STAGES = [
    "transcribe",
    "agent1_voice_comprehension",
    "agent2_risk_classification",
    "agent3_action_generation",
    "agent4_reporting",
]


def pct(values: list[float], p: float) -> float:
    """Nearest-rank percentile. No interpolation: with 30 samples an
    interpolated p95 invents a value that was never observed."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(p / 100 * len(ordered) + 0.5)) - 1))
    return ordered[k]


async def one_run(graph, worker_id: str, patient: Patient) -> dict[str, float]:
    state = {
        "worker_id": worker_id,
        "patient_id": patient.patient_id,
        "patient_name": patient.name,
        "patient_phone": patient.phone,
        "audio_base64": base64.b64encode(SAMPLE_HI.encode()).decode(),
        "language_code": "hi",
    }

    timings: dict[str, float] = {}
    started = time.perf_counter()
    # astream yields after each node, so the gap between yields is that
    # node's wall time. Timing the nodes from inside the pipeline would
    # mean shipping instrumentation in the request path for the sake of
    # a benchmark.
    last = started
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
    args = ap.parse_args()

    settings = get_settings()
    init_db()
    db = SessionLocal()
    try:
        patient = db.query(Patient).first()
        if patient is None:
            worker = Worker(
                name="Benchmark ASHA",
                phone="9000000001",
                pin_hash="not-a-real-hash",
                role="asha",
                sub_centre_id="SC-BENCH-01",
            )
            db.add(worker)
            db.flush()
            patient = Patient(
                worker_id=worker.worker_id,
                name="Benchmark Patient",
                age=32,
                gender="female",
                village="Benchpur",
                phone="9000000002",
                pregnancy_stage="7 months",
            )
            db.add(patient)
            db.commit()
            db.refresh(patient)
        worker_id = patient.worker_id

        graph = build_pipeline_graph(
            get_bhashini_client(settings),
            get_llm_client(settings),
            get_whatsapp_client(settings),
            get_sms_client(settings),
        )

        print(f"SevakAI pipeline latency — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
        print(f"runs={args.runs}  stt_provider={settings.stt_provider}  "
              f"llm_provider={settings.llm_provider}  use_mocks={settings.use_mocks}")
        print()

        # One untimed pass: the first call pays for imports, model
        # construction and connection setup, and reporting that as the
        # typical case would be dishonest in the other direction.
        await one_run(graph, worker_id, patient)

        samples: dict[str, list[float]] = {}
        for i in range(args.runs):
            for node, ms in (await one_run(graph, worker_id, patient)).items():
                samples.setdefault(node, []).append(ms)
            print(f"\r  run {i + 1}/{args.runs}", end="", flush=True, file=sys.stderr)
        print("\r" + " " * 24 + "\r", end="", file=sys.stderr)

        print(f"{'stage':<32}{'p50':>9}{'p95':>9}{'min':>9}{'max':>9}")
        print("-" * 68)
        for node in STAGES + ["TOTAL"]:
            v = samples.get(node)
            if not v:
                continue
            label = node if node != "TOTAL" else "TOTAL (excl. network + DB write)"
            print(f"{label:<32}{pct(v, 50):>8.1f}ms{pct(v, 95):>8.1f}ms"
                  f"{min(v):>8.1f}ms{max(v):>8.1f}ms")

        print()

        # Refuse to issue a verdict on mocked providers.
        #
        # An earlier version printed "p95 = 0.00s (PASS)" against a mock
        # STT and a mock LLM. That number is real in the sense that the
        # code did run that fast, and worthless in every sense that
        # matters -- it is the speed of a base64 decode and a canned
        # string. Printed next to the word PASS it is exactly the sort of
        # figure that walks into a slide and gets a project marked down
        # when somebody asks what was mocked. So the verdict is withheld
        # unless the providers that dominate the time are real ones.
        mocked = [
            name for name, value in (
                ("stt_provider", settings.stt_provider),
                ("llm_provider", settings.llm_provider),
            ) if value == "mock"
        ]
        if settings.use_mocks:
            mocked.append("use_mocks=true")

        total_p95 = pct(samples.get("TOTAL", []), 95)
        if mocked:
            print("NOT A VALID MEASUREMENT — these providers are mocked:")
            for m in mocked:
                print(f"      {m}")
            print()
            print("      The figures above are the speed of a base64 decode and")
            print("      canned strings, not of speech recognition and a language")
            print("      model. They must not be quoted as SevakAI's latency.")
            print()
            print("      For a real number:")
            print("        STT_PROVIDER=whisper LLM_PROVIDER=real USE_MOCKS=false \\")
            print("          python -m scripts.measure_latency --runs 30")
            return 2

        print(f"NFR-P1 target <30s end-to-end: p95 = {total_p95 / 1000:.2f}s "
              f"({'PASS' if total_p95 < 30000 else 'FAIL'})")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
