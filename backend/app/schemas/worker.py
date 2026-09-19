from datetime import date, datetime

from pydantic import BaseModel, Field


class WorkerStats(BaseModel):
    """Real, computed-from-visits stats -- never hardcoded (dashboard roster,
    'how many patients they treated')."""

    worker_id: str
    # The formal staff number (ASHA-PUNE-01-007). Nullable only for the
    # window between a worker row being created and backfill_identity()
    # running -- every dashboard therefore has to tolerate a blank.
    worker_code: str | None = None
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
    # FR: a resolved HIGH case is a separate fact from an overridden risk
    # level -- resolving keeps the historical risk_level as-is (see
    # resolve_risk()) and just records that a supervisor reviewed and
    # closed it out, with a mandatory note (no bare one-click resolve).
    risk_resolved: bool = False
    risk_resolution_note: str | None = None
    resolved_by_name: str | None = None
    resolved_at: datetime | None = None


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


class Colleague(BaseModel):
    """Another ASHA in the same sub-centre, as a name to pick from."""

    worker_id: str
    worker_code: str | None = None
    name: str


class AbsenceSummary(BaseModel):
    absence_id: str
    worker_id: str
    worker_name: str
    worker_code: str | None = None
    covering_worker_id: str
    covering_worker_name: str
    covering_worker_code: str | None = None
    starts_on: date
    ends_on: date
    reason: str | None = None
    # True once the window has actually opened. A booked-but-not-started
    # leave reads very differently to one already in progress, and the app
    # has to be able to say which.
    in_effect: bool = False


class AbsenceListResponse(BaseModel):
    absences: list[AbsenceSummary]


class DeclareAbsenceRequest(BaseModel):
    covering_worker_id: str
    starts_on: date
    ends_on: date
    reason: str | None = Field(default=None, max_length=500)


class MyProfile(BaseModel):
    """What an ASHA sees about herself.

    Her code is the headline. It is the thing she is asked for on a
    referral form and at a block meeting, and before this screen existed
    the only way to find it was to ask somebody with dashboard access.
    """

    worker_id: str
    worker_code: str | None = None
    name: str
    phone: str
    role: str
    sub_centre_id: str | None = None
    language_pref: str
    joined_on: datetime | None = None

    total_patients: int = 0
    total_visits: int = 0

    # Her own leave, booked or in progress.
    my_absence: AbsenceSummary | None = None
    # Anyone whose patients she is currently carrying.
    covering_for: list[AbsenceSummary] = Field(default_factory=list)
