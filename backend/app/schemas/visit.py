from pydantic import BaseModel, Field, model_validator


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
    audio_base64: str | None = Field(default=None, description="Base64-encoded WAV/MP3/M4A clip, ~60s")
    language_code: str = Field(default="hi", description="e.g. hi, mr, ta, te, bn")
    confirmed_transcript: str | None = Field(
        default=None,
        description="Transcript already reviewed/edited by the ASHA. When set, this exact text "
        "is used instead of re-transcribing audio_base64.",
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
    pregnancy_stage: str | None = None
    medication_compliance: str | None = None  # compliant | non_compliant | unknown
    medication_compliance_detail: str | None = None
    social_risk_factors: list[str] = []
    confidence_scores: dict[str, float] = {}


class RiskDriver(BaseModel):
    observation: str
    reason: str


class VoiceVisitResponse(BaseModel):
    """POST /api/v1/visits/voice response body."""

    visit_id: str
    transcript: str
    extracted: ExtractedFields
    risk_level: str
    risk_score: float
    risk_drivers: list[RiskDriver]
    actions_generated: list[dict]
