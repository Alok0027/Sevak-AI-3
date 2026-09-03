# SevakAI

Agentic Voice Intelligence for India's Last-Mile Health Workers -- Deloitte
USI Capstone Program 2026, Team GenSim (Manipal University Jaipur).

An ASHA worker speaks a home-visit observation in her own language; five AI
agents turn that into a structured clinical record, a risk flag, a referral
letter, a WhatsApp message, and an auto-populated government report --
end-to-end in under 30 seconds. Full requirements: `SevakAI SRS.docx` and
`EOI_MUJ_GenSim.pptx` one level up from this folder.

## Status: backend pipeline is real and tested; mobile/dashboard scaffolded

| Component | State |
|---|---|
| `backend/` | **Working.** FastAPI + LangGraph 5-agent pipeline, all 7 API endpoints, JWT/RBAC, synthetic data generator, PDF reports, 10 passing tests. Runs fully offline against mocked Bhashini/LLM/WhatsApp -- see `backend/README.md` for the real-vs-mocked breakdown and how to flip on real API keys. |
| `dashboard/` | **Working.** React + Vite district dashboard (heatmap, metrics, escalations), verified end-to-end against the live backend (screenshot in the delivery notes). `npm install && npm run dev`. |
| `mobile/` | **Code skeleton.** Every screen and service is written (login, patient list, voice recording + offline queue, task list), but needs `flutter create .` run once to generate the native android/ios folders before it's buildable -- see `mobile/README.md`. |

## Fastest way to see it work

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
python -m scripts.seed_synthetic_data
python -m scripts.demo_pipeline
```

This runs the exact SRS section 9 demo scenario (Meera Patil, 28, 7 months
pregnant, BP 140/90, missed iron tablets, husband away) through all four
synchronous agents and prints the transcript, structured record, risk
classification with explainable drivers, and every generated action --
with zero network calls and zero API keys.

Then bring up the full stack:

```bash
# terminal 1
cd backend && uvicorn app.main:app --reload

# terminal 2
cd dashboard && npm install && cp .env.example .env && npm run dev
```

Open http://localhost:5173, sign in as the demo ANM (`9999999901` / `1234`),
and watch the dashboard reflect whatever visits you run through the backend.

## Why some things are mocked

The SRS explicitly flags Bhashini/GenW.AI access and WhatsApp Business API
approval as things that might not be confirmed by Week 1-2 (risk register,
section 11). Rather than block the whole team on external approvals, every
paid/gated dependency (Bhashini speech-to-text, the LLM, WhatsApp) sits
behind an interface with a mock implementation that runs the full pipeline
deterministically offline, and a real implementation ready to go the moment
credentials arrive -- flip `USE_MOCKS=false` in `backend/.env`, nothing else
changes. See `backend/README.md`'s "what's real vs. mocked" table for the
complete picture, including the two pieces (NHM protocol RAG, Agent 1's LLM
extraction) that are real rule-based logic standing in for what SRS section
10 schedules as Week 2 work.

## Layout

```
backend/    FastAPI + LangGraph -- see backend/README.md
mobile/     Flutter (ASHA worker app) -- see mobile/README.md
dashboard/  React (district dashboard) -- see dashboard/README.md
```

## Next steps, in SRS sprint-plan order

1. **Week 2**: real ChromaDB + >=20 NHM protocol documents (`backend/app/services/nhm_protocol_rag.py` has the exact swap point and keeps the same function signature).
2. **Week 2**: register for Bhashini + an LLM API key; flip `USE_MOCKS=false`.
3. **Week 3**: `flutter create .` in `mobile/`, wire `SyncService.start()` after login, test on a real Android 10+/2GB RAM device (FR-07.4).
4. **Week 3**: WhatsApp Business API approval (apply Week 1 Day 1 per the SRS risk register -- long lead time); Twilio SMS as the documented fallback.
5. **Week 4**: `python -m scripts.seed_synthetic_data --full` for the full 500-worker/5,000-patient dataset; rehearse the section 9 demo script on the actual demo hardware.
