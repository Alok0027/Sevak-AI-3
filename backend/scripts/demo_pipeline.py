"""
Runs the exact 5-minute demo scenario from SRS section 9 end-to-end and
prints every agent's output -- this is the fastest way to prove the whole
pipeline works without touching the mobile app or dashboard UI.

Run `python -m scripts.seed_synthetic_data` first (creates the demo worker
Sunita Sharma and patient Meera Patil this script uses).

Usage: python -m scripts.demo_pipeline
"""
import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.db.models.patient import Patient
from app.db.models.worker import Worker
from app.db.session import SessionLocal
from app.services.visit_pipeline import run_voice_visit

# Verbatim from SRS section 9.1, 1:00-1:30.
DEMO_TRANSCRIPT_HI = (
    "Meera Patil, 28 saal, 7 mahine ki pregnancy. Aaj BP 140 over 90 tha. "
    "Usne pichle 2 hafte se iron tablets nahi li. Pati bahar gaya hua hai."
)


async def main() -> None:
    db = SessionLocal()
    settings = get_settings()
    try:
        worker = db.query(Worker).filter(Worker.phone == "9999999999").first()
        patient = db.query(Patient).filter(Patient.name == "Meera Patil").first()
        if worker is None or patient is None:
            print("Demo fixtures not found. Run: python -m scripts.seed_synthetic_data")
            return

        audio_base64 = base64.b64encode(DEMO_TRANSCRIPT_HI.encode("utf-8")).decode("ascii")

        print("=" * 70)
        print("0:30  Sunita opens the app, presses record, speaks in Hindi:")
        print(f"      {DEMO_TRANSCRIPT_HI!r}")
        print("=" * 70)

        response = await run_voice_visit(
            db=db,
            settings=settings,
            worker_id=worker.worker_id,
            patient_id=patient.patient_id,
            audio_base64=audio_base64,
            language_code="hi",
        )

        print(f"\n[Bhashini]  transcript -> {response.transcript!r}")
        print(f"\n[Agent 1]   structured record ->")
        print(json.dumps(response.extracted.model_dump(), indent=2, ensure_ascii=False))
        print(f"\n[Agent 2]   risk = {response.risk_level}  (score {response.risk_score})")
        for d in response.risk_drivers:
            print(f"            - {d.observation}: {d.reason}")
        print(f"\n[Agent 3]   {len(response.actions_generated)} action(s) generated:")
        for a in response.actions_generated:
            print(f"            - [{a['type']}] status={a['status']}")
            if a["type"] != "followup":
                print("              " + a["content"].replace("\n", "\n              "))
        print(f"\n[Agent 4]   HMIS/RCH monthly report updated for {worker.name} "
              f"({worker.worker_id[:8]}...)")
        print(f"\nvisit_id = {response.visit_id}")
        print("=" * 70)
        print("Done. Everything above ran with zero network calls (USE_MOCKS=true).")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
