import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    admin,
    auth,
    dashboard,
    escalations,
    patients,
    reports,
    support,
    sync,
    tasks,
    visits,
    workers,
    notifications,
)
from app.core.config import get_settings
from app.db.session import SessionLocal, backfill_identity, init_db

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()

    # SEED_DEMO_ON_START=true on a fresh deployment, so there is an account
    # to log in with. Idempotent, and wrapped because a seeding failure is
    # not a reason to refuse to serve -- an API that starts with no demo
    # rows is still usable, one that will not start at all is not. The
    # traceback goes to the platform log rather than the void.
    if settings.seed_demo_on_start:
        from scripts.seed_synthetic_data import seed_demo_fixtures

        db = SessionLocal()
        try:
            seed_demo_fixtures(db)
        except Exception:  # noqa: BLE001 -- see above
            logger.exception("demo seeding failed; continuing without it")
        finally:
            db.close()

    # Worker codes, village keys and the phone blind index, for rows that
    # predate those columns.
    #
    # After seeding, not before: the demo accounts are created above and
    # would otherwise go one whole boot without codes. Wrapped for the
    # same reason -- the columns are nullable and every reader tolerates
    # NULL, so a deployment that cannot finish a backfill should still
    # serve and try again next boot rather than refuse to start.
    try:
        backfill_identity()
    except Exception:  # noqa: BLE001
        logger.exception("identity backfill failed; continuing without it")

    yield


app = FastAPI(
    title="SevakAI API",
    description="Agentic Voice Intelligence for India's Last-Mile Health Workers",
    version="1.0.0",
    lifespan=lifespan,
)

# Dashboard (React, different origin during dev) and mobile app both call
# this API. Origins come from CORS_ORIGINS -- see app/core/config.py for why
# the "*" default is a development-only convenience.
_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(visits.router)
app.include_router(patients.router)
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(sync.router)
app.include_router(escalations.router)
app.include_router(tasks.router)
app.include_router(workers.router)
app.include_router(admin.router)
app.include_router(support.router)
app.include_router(notifications.router)
