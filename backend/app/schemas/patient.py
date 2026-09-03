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


class PatientSummary(BaseModel):
    id: str
    name: str
    age: int | None = None
    village: str | None = None
    pregnancy_stage: str | None = None
    risk_status: str | None = None  # HIGH | MEDIUM | LOW | None (no visit yet)
    last_visit: datetime | None = None
    total_visits: int = 0


class PatientListResponse(BaseModel):
    patients: list[PatientSummary]


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
    confidence_scores: dict[str, float] = Field(default_factory=dict)


class PatientVoiceIntakeResponse(BaseModel):
    """Never writes to the DB -- the mobile app pre-fills the Add Patient
    form from this and the ASHA still taps Save herself (review-before-
    submit, same principle as the visit pipeline's transcript display)."""

    transcript: str
    extracted: ExtractedIntakeFields
