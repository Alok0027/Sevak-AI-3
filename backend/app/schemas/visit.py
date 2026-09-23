from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

VALID_RISK_LEVELS = ("HIGH", "MEDIUM", "LOW")


class TranscribeRequest(BaseModel):
    """POST /api/v1/visits/transcribe request body (FR-01.4: transcribe-only,
    no pipeline processing, so the ASHA can review before anything downstream
    runs)."""

    audio_base64: str = Field(description="Base64-encoded WAV/MP3/M4A clip, ~60s")
    language_code: str = Field(default="hi", description="e.g. hi, mr, ta, te, bn")


class TranscribeResponse(BaseModel):
    transcript: str


class VoiceVisitRequest(BaseModel):
    """POST /api/v1/visits/voice request body (SRS section 7, table 19).

    FR-01.4: either submit raw audio directly (it gets transcribed here, as
    before), or submit `confirmed_transcript` -- the text the ASHA already
    reviewed via POST /visits/transcribe -- in which case that exact text
    is used and audio_base64 is not needed at all."""

    worker_id: str
    patient_id: str
    client_request_id: str | None = Field(default=None, min_length=1, max_length=100)
    audio_base64: str | None = Field(default=None, description="Base64-encoded WAV/MP3/M4A clip, ~60s")
    language_code: str = Field(default="hi", description="e.g. hi, mr, ta, te, bn")
    confirmed_transcript: str | None = Field(
        default=None,
        description="Transcript already reviewed/edited by the ASHA. When set, this exact text "
        "is used instead of re-transcribing audio_base64.",
    )
    confirmed_extracted: "ExtractedFields | None" = Field(
        default=None,
        description="Clinical fields already reviewed/corrected by the ASHA via "
        "POST /visits/extract. When set, Agent 1 is skipped and these exact values feed "
        "risk scoring -- a misheard BP corrected here never reaches the classifier.",
    )

    @model_validator(mode="after")
    def _require_audio_or_transcript(self) -> "VoiceVisitRequest":
        if not self.audio_base64 and not self.confirmed_transcript:
            raise ValueError("Provide either audio_base64 or confirmed_transcript")
        return self


class ExtractedFields(BaseModel):
    """Agent 1 output shape (FR-02.5)."""

    patient_name: str | None = None
    age: int | None = None
    relationship_to_head: str | None = None
    bp_systolic: int | None = None
    bp_diastolic: int | None = None
    weight_kg: float | None = None
    temperature_c: float | None = None
    # Separate readings: the NHM cutoffs differ (fasting >=126 mg/dL vs
    # random >=200), so a single undifferentiated number can't be scored.
    blood_sugar_fasting: int | None = None
    blood_sugar_random: int | None = None
    # Reported violence or injury, e.g. ["physical violence", "injury
    # reported"]. Kept apart from social_risk_factors because those nudge
    # the score while these escalate outright -- an ASHA describing an
    # assault is reporting an emergency, not a background stressor.
    violence_or_injury: list[str] = []
    # Danger signs from NHM antenatal care's immediate-referral list, e.g.
    # ["Severe headache, with or without blurred vision"]. A separate field
    # rather than free-text symptoms, and separate from social_risk_factors,
    # for the same reason violence_or_injury is separate: these escalate
    # outright instead of nudging a score.
    #
    # It exists because nothing captured them before. An ASHA saying "sir
    # mein tez dard aur dhundla dikh raha hai" had those words dropped by
    # Agent 1, so the classifier scored her normal BP and answered LOW,
    # over the words "no abnormal findings recorded". The corpus calls
    # these the presenting signs of imminent eclampsia.
    danger_signs: list[str] = []
    pregnancy_stage: str | None = None
    medication_compliance: str | None = None  # compliant | non_compliant | unknown
    medication_compliance_detail: str | None = None
    social_risk_factors: list[str] = []
    confidence_scores: dict[str, float] = {}


class ExtractRequest(BaseModel):
    """POST /api/v1/visits/extract request body.

    The transcript-review step (FR-01.4) lets the ASHA fix a misheard word;
    this is the same idea for the structured fields that word becomes. It
    takes a transcript rather than audio because it runs *after* she has
    confirmed the text -- re-extracting from the recording could hand back
    fields that contradict the transcript she just corrected."""

    transcript: str = Field(min_length=1)


class ExtractResponse(BaseModel):
    extracted: ExtractedFields


# confirmed_extracted is annotated as a string above because ExtractedFields
# is defined below it; resolve that now the name exists.
VoiceVisitRequest.model_rebuild()


class RiskDriver(BaseModel):
    observation: str
    reason: str
    # Where the reason came from, when it came from the NHM corpus rather
    # than the hardcoded thresholds. Optional because the deterministic
    # rules have no retrieved source to point at -- and because every
    # driver written before retrieval existed is still valid, just
    # uncited. An absent source means "this is the threshold engine",
    # never "the citation got lost".
    source: str | None = None       # "<document title> — <section>"
    source_url: str | None = None


class VoiceVisitResponse(BaseModel):
    """POST /api/v1/visits/voice response body."""

    visit_id: str
    transcript: str
    extracted: ExtractedFields
    risk_level: str
    risk_score: float
    risk_drivers: list[RiskDriver]
    actions_generated: list[dict]


class RiskOverrideRequest(BaseModel):
    """POST /api/v1/visits/{visit_id}/risk-override request body (FR-03.3).

    The reason is mandatory and free-text, not a dropdown -- the point is a
    human-readable explanation an ANM/BMO reviewing the audit trail can
    actually understand, not just a category code."""

    new_risk_level: str = Field(description="HIGH, MEDIUM, or LOW")
    reason: str = Field(min_length=5, max_length=500, description="Why this correction is being made")

    @field_validator("new_risk_level")
    @classmethod
    def _valid_risk_level(cls, v: str) -> str:
        v = v.upper()
        if v not in VALID_RISK_LEVELS:
            raise ValueError(f"new_risk_level must be one of {VALID_RISK_LEVELS}")
        return v

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reason cannot be blank")
        return v.strip()


class RiskOverrideResponse(BaseModel):
    visit_id: str
    patient_id: str
    previous_risk_level: str | None
    new_risk_level: str
    reason: str
    overridden_by: str  # worker_id
    overridden_by_name: str
    overridden_by_role: str  # asha | anm | bmo
    overridden_at: datetime


class VisitAmendRequest(BaseModel):
    """PATCH /api/v1/visits/{visit_id}/record -- correct what was recorded.

    FR-01.4 lets an ASHA review the transcript *before* the pipeline runs.
    Nothing let her fix it afterwards. A blood pressure misheard as 140/90
    when the cuff read 120/80 kept driving the risk score, the referral
    letter and the follow-up deadline for the life of the record, and the
    only tool available -- a risk override -- changes the label while
    leaving the wrong reading sitting underneath it, which is worse than
    either being wrong on its own.

    Only the fields sent are amended. `None` means "leave alone"; the
    explicit `clear_*` flags are how a reading is removed outright, for a
    value that was never actually taken.
    """

    bp_systolic: int | None = Field(default=None, ge=40, le=300)
    bp_diastolic: int | None = Field(default=None, ge=20, le=200)
    temperature_c: float | None = Field(default=None, ge=30.0, le=45.0)
    weight_kg: float | None = Field(default=None, ge=1.0, le=300.0)
    blood_sugar_fasting: int | None = Field(default=None, ge=20, le=600)
    blood_sugar_random: int | None = Field(default=None, ge=20, le=600)
    pregnancy_stage: str | None = None
    medication_compliance: str | None = None

    clear_bp: bool = False
    clear_temperature: bool = False
    clear_blood_sugar: bool = False
    clear_pregnancy_stage: bool = False

    reason: str = Field(min_length=5, max_length=500)


class VisitAmendResponse(BaseModel):
    visit_id: str
    patient_id: str
    amended_fields: dict
    previous_risk_level: str | None
    new_risk_level: str
    risk_score: float
    risk_drivers: list[RiskDriver]
    override_cleared: bool
    amended_by: str
    amended_at: datetime
