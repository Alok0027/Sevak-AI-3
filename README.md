# SevakAI

Agentic Voice Intelligence for India's Last-Mile Health Workers -- Deloitte
USI Capstone Program 2026, Team GenSim (Manipal University Jaipur).

An ASHA worker speaks a home-visit observation in her own language; five AI
agents turn that into a structured clinical record, a risk flag, a referral
letter, a WhatsApp message, and an auto-populated government report --
end-to-end in under 30 seconds. Full requirements: `SevakAI SRS.docx` and
`EOI_MUJ_GenSim.pptx` one level up from this folder.

## Live

| | |
|---|---|
| Dashboard (ANM / BMO / Admin) | https://sevak-ai-3-phi.vercel.app |
| API | https://sevakai-api.onrender.com — health check at `/health` |
| Mobile | `flutter build apk --release` (see Deployment below) |

Demo logins, all PIN `1234`:

| Role | Phone |
|---|---|
| ASHA (Sunita Sharma) | 9999999999 |
| ANM (Dr. Rekha Joshi) | 9999999901 |
| BMO (Dr. Vikram Rao) | 9999999902 |
| Admin | 9999999903 |

The API sleeps after 15 minutes idle on Render's free tier. The first
request wakes it and takes about 50 seconds; everything after that is
immediate. Open it a minute before you need it.

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
complete picture, including what is retrieval-grounded and what is
deterministic rules.

## Layout

```
backend/    FastAPI + LangGraph -- see backend/README.md
mobile/     Flutter (ASHA worker app) -- see mobile/README.md
dashboard/  React (district dashboard) -- see dashboard/README.md
```

## Next steps, in SRS sprint-plan order

2. **Week 2**: register for Bhashini + an LLM API key; flip `USE_MOCKS=false`.
3. **Week 3**: `flutter create .` in `mobile/`, wire `SyncService.start()` after login, test on a real Android 10+/2GB RAM device (FR-07.4).
4. **Week 3**: WhatsApp Business API approval (apply Week 1 Day 1 per the SRS risk register -- long lead time); Twilio SMS as the documented fallback.
5. **Week 4**: `python -m scripts.seed_synthetic_data --full` for the full 500-worker/5,000-patient dataset; rehearse the section 9 demo script on the actual demo hardware.

## Deployment

Three pieces, three places: the API is a container, the dashboard is a
static build, the mobile app is an APK you hand out. Only the first two
"deploy" in the usual sense.

Deploy in this order — the dashboard needs the API's URL, and the API needs
the dashboard's origin, so one has to go first and be told about the other
afterwards.

### 1. Backend → Render

`render.yaml` is a blueprint: it creates the web service and its Postgres
together and wires `DATABASE_URL` between them.

  Render → New → Blueprint → select this repo.

Two values are deliberately not in the blueprint and must be set in the
Render dashboard before the first deploy finishes:

  ENCRYPTION_KEY   generate with:  cd backend && python scripts/generate_encryption_key.py
  CORS_ORIGINS     your Vercel URL, e.g. https://sevakai.vercel.app (no trailing slash)

`ENCRYPTION_KEY` must be base64 of exactly 32 raw bytes — the script emits
that. It is not auto-generated because every patient row encrypted with it
is unreadable without it; keep a copy somewhere other than Render, and do
not rotate it casually.

Everything external (`STT_PROVIDER`, `LLM_PROVIDER`, `WHATSAPP_PROVIDER`,
`SMS_PROVIDER`) ships set to `mock`, so a blueprint deploy with no API keys
still boots and serves a working demo. Turn each one on as its credentials
go in. `SEED_DEMO_ON_START=true` creates the SRS section 9 accounts on an
empty database, because a fresh Postgres has no one to log in as and the
free tier gives you no shell to make one; it is idempotent, so turn it off
once there is real data.

Two things about the free tier worth knowing before a live demo: the
service sleeps after 15 minutes idle and takes ~50s to answer the request
that wakes it, and the free Postgres expires after 30 days. Open the URL a
minute before you present.

`STT_PROVIDER=whisper` will not work on Render. `faster-whisper` is not in
the image on purpose (see `backend/Dockerfile`); local Whisper is for
laptops, `pip install -r requirements-local-asr.txt`.

### 2. Dashboard → Vercel

  Vercel → Add New → Project → this repo → Root Directory: `dashboard`

`dashboard/vercel.json` sets the framework, the output directory, and the
SPA rewrite. The rewrite is the one that matters: without it, refreshing on
`/bmo` asks Vercel for a file called `bmo`, gets a 404, and the app looks
broken to anyone who does not enter through the front door.

Set one environment variable:

  VITE_API_BASE_URL = https://sevakai-api.onrender.com   (your Render URL)

Vite inlines `VITE_*` at build time, so changing it needs a redeploy, not
just a restart. Then go back and set `CORS_ORIGINS` on Render to this
site's origin.

### 3. Mobile → an APK

The app has no app-store presence; you build a file and share it.

```bash
cd mobile
flutter build apk --release --dart-define=SEVAKAI_API=https://sevakai-api.onrender.com
# build/app/outputs/flutter-apk/app-release.apk
```

The `--dart-define` is a belt-and-braces override — `api_client.dart`
already defaults to the deployed URL, so an APK built without it still
works. Pass it when your service name differs from `sevakai-api`.

For local development against a laptop, point it at the LAN instead:

```bash
flutter run --dart-define=SEVAKAI_API=http://192.168.1.42:8000
```

Plain `http` works in debug builds only. `android/app/src/debug/
AndroidManifest.xml` permits cleartext there and nowhere else, so a release
build must be given an `https` URL.

### What is not set up

No Alembic migrations. Tables are created by `init_db()` at startup, which
is correct exactly once, against an empty database. `create_all()` never
alters a table that already exists, so the first model change after a
deploy will leave Postgres missing a column and the error will arrive at
runtime, in whichever endpoint touches it first. Add Alembic before the
schema next changes, not after.

CI does not run the test suite on push. Run it before deploying:

```bash
cd backend && PYTHONPATH=. pytest -q     # 98 tests, no network required
```
