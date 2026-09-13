"""A visit nothing could be read from must not look like a healthy one.

Before this, `classify(ExtractedFields())` returned LOW with the driver
"All extracted vitals and compliance signals are within normal NHM range."
-- a factual claim the system could not support, because nothing had been
measured. A failed transcription and a patient in good health produced
byte-identical output, so the ASHA saw a calm green LOW either way.

That is the wrong way round: a silent failure should read louder than a
normal result, not the same.
"""
import asyncio

from app.agents.agent2_risk_classification import classify, classify_with_llm
from app.agents.agent3_action_generation import FOLLOWUP_DAYS, generate
from app.schemas.visit import ExtractedFields
from app.services.llm_client import LLMClientBase
from app.services.nhm_protocol_rag import has_clinical_signal
from app.services.sms_client import MockSmsClient
from app.services.whatsapp_client import MockWhatsAppClient


def test_nothing_extracted_is_unassessed_not_low():
    assert classify(ExtractedFields()).risk_level == "UNASSESSED"


def test_measured_and_normal_is_still_low():
    """The distinction has to cut both ways, or it is just a rename."""
    fields = ExtractedFields(bp_systolic=110, bp_diastolic=70, medication_compliance="compliant")
    assert classify(fields).risk_level == "LOW"


def test_unassessed_does_not_claim_anything_was_in_range():
    result = classify(ExtractedFields())
    text = " ".join(f"{d.observation} {d.reason}" for d in result.drivers).lower()
    assert "within normal" not in text
    assert "nothing" in text or "no clinical observations" in text


def test_identifying_details_alone_are_not_clinical_signal():
    """A transcript yielding only "Meera, 28" says who the visit was
    about and nothing about how she is."""
    assert not has_clinical_signal(ExtractedFields(patient_name="Meera Patil", age=28))
    assert not has_clinical_signal(ExtractedFields(pregnancy_stage="7 months"))


def test_medication_unknown_is_absence_not_observation():
    # Agent 1 saying it could not tell is not a finding.
    assert not has_clinical_signal(ExtractedFields(medication_compliance="unknown"))
    # Somebody answering "yes, taking them" is.
    assert has_clinical_signal(ExtractedFields(medication_compliance="compliant"))


def test_a_single_vital_is_enough_to_assess():
    assert has_clinical_signal(ExtractedFields(temperature_c=37.0))
    assert classify(ExtractedFields(temperature_c=37.0)).risk_level == "LOW"


def test_half_a_blood_pressure_is_not_a_reading():
    """The rules score BP as a pair; a lone systolic cannot be graded."""
    assert not has_clinical_signal(ExtractedFields(bp_systolic=150))


class _AlwaysLowLLM(LLMClientBase):
    """Stands in for what a real LLM does with an empty record: it answers
    LOW, fluently, because the prompt tells it to return LOW when nothing
    abnormal was observed and it cannot tell that apart from observing
    nothing."""

    def __init__(self):
        self.called = False

    async def complete(self, system: str, user: str) -> str:
        self.called = True
        return ('{"risk_level": "LOW", "risk_score": 0.0, "drivers": '
                '[{"observation": "No abnormal findings", "reason": "All vitals normal."}]}')


def test_llm_is_never_asked_to_classify_an_empty_record():
    llm = _AlwaysLowLLM()
    result = asyncio.run(classify_with_llm(ExtractedFields(), llm))
    assert result.risk_level == "UNASSESSED"
    assert not llm.called, "the empty record reached the LLM, which will answer LOW"


def test_llm_still_runs_when_there_is_something_to_classify():
    llm = _AlwaysLowLLM()
    fields = ExtractedFields(bp_systolic=118, bp_diastolic=76)
    result = asyncio.run(classify_with_llm(fields, llm))
    assert llm.called
    assert result.risk_level == "LOW"


def test_unassessed_follows_up_tomorrow_not_in_a_month():
    assert FOLLOWUP_DAYS["UNASSESSED"] == 1
    assert FOLLOWUP_DAYS["UNASSESSED"] < FOLLOWUP_DAYS["LOW"]


def test_unassessed_visit_messages_nobody_and_asks_for_a_re_record():
    """No finding to report, so nothing goes to the patient -- 'your risk
    status is unknown' alarms without informing. The outstanding work is
    ours, and it is redoing the visit."""
    actions = asyncio.run(generate(
        extracted=ExtractedFields(),
        risk_level="UNASSESSED",
        risk_drivers=[],
        patient_name="Meera Patil",
        patient_phone="9876543210",
        llm_client=None,
        whatsapp_client=MockWhatsAppClient(),
        sms_client=MockSmsClient(),
    ))
    kinds = {a["type"] for a in actions}
    assert kinds == {"followup"}, f"expected only a follow-up, got {kinds}"
    assert "re-record" in actions[0]["content"].lower()
