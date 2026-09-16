from datetime import datetime

from pydantic import BaseModel, Field


class PatientCreate(BaseModel):
    """FR-07.2 prerequisite: an ASHA worker must be able to register a new
    patient before she can record a visit for them -- only `name` is
    required, everything else can be filled in or corrected later."""

    name: str = Field(min_length=1)
    age: int | None = None
    gender: str | None = None
    village: str | None = None
    phone: str | None = None
    pregnancy_stage: str | None = None

    # The number on her MCP card. Optional: an ASHA meeting a woman at her
    # door before the sub-centre has registered her has none to type, and
    # refusing the record until she does pushes the work back onto paper.
    rch_number: str | None = None

    # ANM only. She holds the sub-centre's RCH register in real life and
    # hands the line-list down to her workers; this is the field that lets
    # her do it here. An ASHA passing it for somebody else is refused --
    # a worker who could file patients onto a colleague's list could also
    # quietly empty her own.
    worker_id: str | None = None
    # Baseline readings taken at registration. Per-visit measurements live
    # on the visit record (app.schemas.visit.ExtractedFields) -- these are
    # the starting point later visits are compared against, not a risk input.
    bp_systolic: int | None = None
    bp_diastolic: int | None = None
    blood_sugar_fasting: int | None = None
    blood_sugar_random: int | None = None


class TriageFields(BaseModel):
    """What every list needs in order to put the right person first.

    Computed server-side by app/services/patient_priority.py and shared by
    the ASHA's list, the ANM's sub-centre view and the BMO's district
    table, so a supervisor and the worker she supervises can never be
    looking at differently-ordered copies of the same ward.

    [attention_reason] is a key, not a sentence. The app says it in six
    languages and the dashboard says it in English; neither should be
    re-translating a phrase the server invented.
    """

    # Higher is sooner. Only meaningful as a comparison -- never shown.
    priority_score: int = 0
    needs_attention: bool = False
    attention_reason: str | None = None  # high_risk | overdue | due_today
    hours_overdue: int = 0
    open_followups: int = 0
    next_followup_due: datetime | None = None


class PatientSummary(TriageFields):
    id: str
    name: str
    rch_number: str | None = None
    # Set only when this patient is on her list because she is covering
    # for somebody who is away -- the name of that somebody. Null for her
    # own patients, which is almost all of them.
    covering_for: str | None = None
    age: int | None = None
    village: str | None = None
    pregnancy_stage: str | None = None
    risk_status: str | None = None  # HIGH | MEDIUM | LOW | None (no visit yet)
    last_visit: datetime | None = None
    total_visits: int = 0


class PatientListResponse(BaseModel):
    patients: list[PatientSummary]
    # So a list can head itself "3 need attention today" without counting
    # client-side -- and so a caller that pages this later still gets the
    # true total rather than the count of whatever fitted on page one.
    attention_count: int = 0


class PatientDirectoryEntry(TriageFields):
    """One row in the ANM/BMO cross-worker patient directory (FR-08 drill-
    down) -- unlike PatientSummary, which is one ASHA's own patient list,
    this spans every ASHA in scope, so it also carries gender (a filter
    dimension), registration date, and which worker treats her."""

    id: str
    name: str
    rch_number: str | None = None
    age: int | None = None
    gender: str | None = None
    village: str | None = None
    pregnancy_stage: str | None = None
    risk_status: str | None = None  # HIGH | MEDIUM | LOW | None (no visit yet)
    last_visit: datetime | None = None
    total_visits: int = 0
    registered_at: datetime
    worker_id: str
    worker_name: str
    sub_centre_id: str | None = None


class PatientDirectoryResponse(BaseModel):
    patients: list[PatientDirectoryEntry]
    attention_count: int = 0


class PatientVoiceIntakeRequest(BaseModel):
    """FR-07.2 voice-fill: ASHA speaks the new patient's details instead of
    typing them. Same shape as VoiceVisitRequest's audio fields."""

    audio_base64: str
    language_code: str = "hi"


class ExtractedIntakeFields(BaseModel):
    name: str | None = None
    age: int | None = None
    gender: str | None = None
    village: str | None = None
    phone: str | None = None
    pregnancy_stage: str | None = None
    # Fasting and random blood sugar stay separate because the NHM cutoffs
    # differ (>=126 vs >=200 mg/dL) -- one undifferentiated number can't be
    # judged against either.
    bp_systolic: int | None = None
    bp_diastolic: int | None = None
    blood_sugar_fasting: int | None = None
    blood_sugar_random: int | None = None
    confidence_scores: dict[str, float] = Field(default_factory=dict)


class PatientVoiceIntakeResponse(BaseModel):
    """Never writes to the DB -- the mobile app pre-fills the Add Patient
    form from this and the ASHA still taps Save herself (review-before-
    submit, same principle as the visit pipeline's transcript display)."""

    transcript: str
    extracted: ExtractedIntakeFields


class ReassignRequest(BaseModel):
    """Move a patient, or a whole caseload, to another ASHA."""

    to_worker_id: str
    # Required, and it is the point. An ASHA leaving, going on maternity
    # leave, or being replaced are different facts about a real person's
    # employment, and six months later the audit log is the only place
    # anybody can find out which one happened.
    reason: str = Field(min_length=5, max_length=500)


class ReassignResult(BaseModel):
    moved: int
    from_worker_id: str
    to_worker_id: str
    to_worker_name: str
