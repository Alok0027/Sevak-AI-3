"""Shared state object threaded through the LangGraph pipeline (Agent 1 -> 4).

SRS section 5.2 "Data Flow -- Single Home Visit" defines exactly this
sequence of handoffs: Bhashini -> Agent1 -> Agent2 -> {Agent3, Agent4}.
Agent 5 (escalation) is not part of this synchronous graph -- it's a
background monitor (see agents/agent5_escalation.py) that scans risk_flags
on a timer, matching FR-06.1's 48-hour threshold rather than the <30s
end-to-end latency target for the synchronous path (NFR-P1).
"""
from typing import TypedDict

from app.schemas.visit import ExtractedFields, RiskDriver


class PipelineState(TypedDict, total=False):
    # inputs
    worker_id: str
    patient_id: str
    patient_name: str
    patient_phone: str | None
    audio_base64: str
    language_code: str
    # FR-01.4: when set, the ASHA has already reviewed/edited the transcript
    # via POST /visits/transcribe -- node_transcribe uses this verbatim
    # instead of re-running STT, so what she confirmed is exactly what
    # feeds risk scoring, not a possibly-different re-transcription.
    confirmed_transcript: str
    # Same principle one step further down: when set, the ASHA has reviewed
    # the extracted clinical fields via POST /visits/extract and corrected
    # anything misheard, so node_agent1 uses these verbatim. A wrong BP is
    # worse than a wrong word -- it drives the risk classification directly.
    confirmed_extracted: ExtractedFields

    # Agent 1 output
    transcript: str
    extracted: ExtractedFields

    # Agent 2 output
    risk_level: str
    risk_score: float
    risk_drivers: list[RiskDriver]

    # Agent 3 output
    actions: list[dict]

    # Agent 4 output
    hmis_fields: dict

    # bookkeeping
    visit_id: str
