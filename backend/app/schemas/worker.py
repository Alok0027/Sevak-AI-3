from datetime import datetime

from pydantic import BaseModel


class WorkerStats(BaseModel):
    """Real, computed-from-visits stats -- never hardcoded (dashboard roster,
    'how many patients they treated')."""

    worker_id: str
    name: str
    phone: str
    sub_centre_id: str | None
    language_pref: str
    total_patients: int
    total_visits: int
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    pending_followups: int
    last_visit_at: datetime | None


class WorkerRosterResponse(BaseModel):
    workers: list[WorkerStats]


class PatientHistoryEntry(BaseModel):
    """One entry in a worker's or patient's visit timeline."""

    visit_id: str
    patient_id: str
    patient_name: str
    created_at: datetime
    risk_level: str | None
    transcript: str | None
    extracted: dict | None


class WorkerHistoryResponse(BaseModel):
    worker: WorkerStats
    visits: list[PatientHistoryEntry]


class PatientHistoryResponse(BaseModel):
    patient_id: str
    patient_name: str
    worker_id: str
    worker_name: str
    village: str | None
    age: int | None
    pregnancy_stage: str | None
    visits: list[PatientHistoryEntry]
