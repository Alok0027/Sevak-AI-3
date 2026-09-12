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
    # FR-03.3: risk_level above already reflects an override (an ASHA/ANM/BMO
    # correction wins over the AI's original call everywhere it's read from
    # -- dashboard, escalations, reports). These fields are what let the UI
    # show *that* it was corrected, who corrected it, and why -- instead of
    # just a silent number or a vague "corrected by supervisor".
    risk_overridden: bool = False
    risk_override_reason: str | None = None
    overridden_by_name: str | None = None
    overridden_by_role: str | None = None  # asha | anm | bmo


class WorkerHistoryResponse(BaseModel):
    worker: WorkerStats
    visits: list[PatientHistoryEntry]


class PatientHistoryResponse(BaseModel):
    """A patient's record and her full visit timeline.

    Carries the whole registration record, not just the name: an ASHA
    opening this on a doorstep needs the baseline readings to compare
    today's against, and the phone number to call if she isn't home.
    Fetching those separately would mean a second round trip on a
    connection that may not survive one.
    """

    patient_id: str
    patient_name: str
    worker_id: str
    worker_name: str
    village: str | None
    age: int | None
    gender: str | None = None
    phone: str | None = None
    pregnancy_stage: str | None
    # Recorded once at registration; the reference point later visits are
    # read against.
    bp_systolic: int | None = None
    bp_diastolic: int | None = None
    blood_sugar_fasting: int | None = None
    blood_sugar_random: int | None = None
    registered_at: datetime | None = None
    visits: list[PatientHistoryEntry]
