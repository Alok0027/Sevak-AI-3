# SevakAI Backend

FastAPI + LangGraph implementation of the 5-agent pipeline described in the
SRS (section 5, FR-01 through FR-06). Every external dependency sits behind
an interface with both a mock and a real implementation, chosen per-provider
by environment variable -- so it runs fully offline with no keys, and the
same code runs live once keys are in. The table below says which is which
*as currently configured*, because "it's all mocked" stopped being true and
a stale answer to that question is worse than none.

## Quick start

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate     # optional but recommended
pip install -r requirements.txt

cp -n .env.example .env       # -n: never clobber an .env that already holds real keys

python -m scripts.seed_synthetic_data     # creates demo worker/patient + a random dev dataset
python -m scripts.demo_pipeline           # runs the SRS section 9 demo scenario end-to-end, prints every agent's output

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000   # API on http://localhost:8000, docs at /docs
```

`--host 0.0.0.0` matters: without it, uvicorn only accepts connections from the machine it's running on (`127.0.0.1`), so the mobile app on a phone -- or the dashboard on a different device -- can't reach it even though the server logs show it's up. With `0.0.0.0`, it also answers on your machine's LAN IP (e.g. `192.168.x.x:8000`), which is what `mobile/lib/services/api_client.dart`'s `baseUrl` needs to point at. That LAN IP can change (new network, DHCP renewal), so if the mobile app suddenly can't reach the backend, check your machine's current IP first.

Demo login (created by the seed script): phone `9999999999`, PIN `1234` (ASHA worker, Sunita Sharma).
Supervisor logins: ANM `9999999901`, BMO `9999999902`, Admin `9999999903` (all PIN `1234`).

Run the test suite: `python -m pytest`

## What's real vs. mocked right now

| Piece | Status |
|---|---|
| FastAPI app, routing, JWT auth, RBAC | Real |
| SQLAlchemy models / DB (SQLite dev, Postgres via `DATABASE_URL`) | Real |
| LangGraph 5-agent wiring (Agents 1-4 synchronous, Agent 5 background) | Real |
| Agent 1 entity extraction | Real regex/rule-based parser (works offline). Swap point for an LLM call is marked in `app/agents/agent1_voice_comprehension.py`. |
| Agent 2 NHM risk classification | Retrieval over the NHM corpus in `nhm_corpus/` (`app/services/nhm_retrieval.py`), with the thresholds in `nhm_protocol_rag.py` as a floor the retrieved reasoning cannot go below. `RETRIEVAL_PROVIDER=lexical` (default, BM25, no model) \| `chroma` \| `none`. |
| Agent 3 referral/WhatsApp/follow-up generation | Real logic, template-based text. Swap point for LLM-drafted local-language text in `app/agents/agent3_action_generation.py`. |
| Agent 4 HMIS/RCH auto-population + PDF | Real, aggregates actual visit rows. |
| Agent 5 escalation monitor | Real logic; wire `check_and_escalate()` to a scheduler for production (currently also runs inline on every `GET /escalations/pending`). |
| Bhashini speech-to-text | **Selected by `STT_PROVIDER`**, not by `USE_MOCKS`. The committed `.env` and `render.yaml` both set `bhashini`, i.e. the real two-step ULCA flow in `app/services/bhashini_client.py`. `mock` decodes the base64 payload as UTF-8 text (how the seed/demo scripts fake "audio"); `whisper` runs `faster-whisper` locally. **Accuracy has never been measured on any provider** -- see `docs/EVIDENCE.md` section 2 before quoting a number. |
| LLM | **Selected by `LLM_PROVIDER`.** Both `.env` and `render.yaml` set `real` (Groq, `openai/gpt-oss-120b`). Agents 1 and 2 fall back to their rule-based paths if a call fails or returns malformed JSON; Agent 4 never needed an LLM. |
| WhatsApp Business API | **Selected by `WHATSAPP_PROVIDER`**: `meta` in both `.env` and `render.yaml`. An explicit `mock` means mock even when `USE_MOCKS=false`; leaving the variable unset keeps the old `USE_MOCKS`-driven behaviour. |
| Supervisor alerts (FR-03.4 / FR-06.1) | Real logic, **no delivery channel configured**: dispatch is SMS-only by design, and `render.yaml` ships `SMS_PROVIDER=mock`, so alerts are built and left `pending` rather than sent. Set `SMS_PROVIDER=real` with the Twilio credentials to actually page anyone. |

Each provider switch is independent, so speech can be live while WhatsApp
stays mocked. No code changes are required either way -- every service
module already has a real implementation behind the same interface as its
mock, selected by `get_*_client(settings)`.

To force everything offline for a rehearsal, set `STT_PROVIDER`,
`LLM_PROVIDER`, `WHATSAPP_PROVIDER` and `SMS_PROVIDER` to `mock`.
`scripts/demo_pipeline.py` does this for itself, so it prints the demo
regardless of what `.env` says.

## Layout

```
app/
  agents/     Agent 1-5 logic + the LangGraph StateGraph wiring (graph.py)
  api/        FastAPI routers, one file per resource, matching SRS section 7
  core/       settings (config.py) and JWT/password hashing (security.py)
  db/         SQLAlchemy models (one file per table, SRS section 6) + session
  schemas/    Pydantic request/response models
  services/   External integrations (Bhashini/LLM/WhatsApp) + NHM retrieval + PDF generation
scripts/
  seed_synthetic_data.py   Faker-based dataset (--full for the SRS-spec 500 workers/5,000 patients)
  demo_pipeline.py         Runs the SRS section 9 demo scenario directly (no HTTP needed)
tests/        pytest suite: agent-level unit tests + a full API smoke test
```

## API endpoints (SRS section 7 / table 19)

All except `/auth/login` require `Authorization: Bearer <token>` and enforce
role checks server-side (`app/api/deps.py::require_roles`).

- `POST /api/v1/auth/login` -- `{phone, pin}` -> JWT
- `POST /api/v1/visits/voice` -- the core pipeline (asha role)
- `GET /api/v1/patients/{worker_id}` -- patient list with risk badges
- `GET /api/v1/dashboard/heatmap`, `GET /api/v1/dashboard/metrics` -- anm/bmo/admin
- `GET /api/v1/reports/hmis/{worker_id}/{month}/{year}` (+ `/pdf`) -- HMIS report
- `POST /api/v1/sync/batch` -- offline queue flush; runs full pipeline per queued voice record
- `GET /api/v1/escalations/pending` -- anm/bmo/admin

## Next (per SRS section 10 sprint plan)

- Grow `nhm_corpus/` beyond its six documents; the retriever reads every `.md` there at startup, so adding one needs no code change and no re-index.
- Week 3: point the Flutter app and React dashboard (see `../mobile`, `../dashboard`) at this API.
- Week 4: register real Bhashini/LLM/WhatsApp credentials, flip `USE_MOCKS=false`, load-test with `--full` synthetic dataset.
