from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, auth, dashboard, escalations, patients, reports, sync, tasks, visits, workers
from app.db.session import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="SevakAI API",
    description="Agentic Voice Intelligence for India's Last-Mile Health Workers",
    version="1.0.0",
    lifespan=lifespan,
)

# Dashboard (React, different origin during dev) and mobile app both call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to real origins before any non-demo deployment
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
