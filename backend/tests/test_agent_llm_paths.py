"""Covers the real-LLM branch of Agent 1 / Agent 2 added in graph.py --
extract_with_llm() / classify_with_llm(). The mock-path behaviour is
already covered by test_agent1_extraction.py / test_agent2_risk.py (which
call extract()/classify() directly); this file is the "does the real
branch actually work, and does it fall back safely" check, using a fake
LLMClientBase so it needs no network access and no API key.
"""
import asyncio

from app.agents.agent1_voice_comprehension import extract, extract_with_llm
from app.agents.agent2_risk_classification import classify, classify_with_llm
from app.schemas.visit import ExtractedFields
from app.services.llm_client import LLMClientBase


class _FakeLLMClient(LLMClientBase):
    """Not MockLLMClient on purpose -- extract_with_llm()/classify_with_llm()
    branch on isinstance(..., MockLLMClient), so a fake real client is the
    only way to exercise the real-call code path without network access."""

    def __init__(self, response: str):
        self.response = response

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        return self.response


def test_agent1_real_path_parses_llm_json():
    fake = _FakeLLMClient('{"patient_name": "Meera Patil", "age": 28, "bp_systolic": 140, '
                           '"bp_diastolic": 90, "medication_compliance": "non_compliant"}')
    fields = asyncio.run(extract_with_llm("irrelevant transcript", fake))
    assert fields.patient_name == "Meera Patil"
    assert fields.age == 28
    assert fields.bp_systolic == 140
    assert fields.medication_compliance == "non_compliant"


def test_agent1_real_path_strips_markdown_fences():
    fake = _FakeLLMClient('```json\n{"patient_name": "Ramesh"}\n```')
    fields = asyncio.run(extract_with_llm("irrelevant transcript", fake))
    assert fields.patient_name == "Ramesh"


def test_agent1_real_path_falls_back_to_regex_on_bad_json():
    transcript = "Meera Patil, 28 saal, BP 140 over 90 tha."
    fake = _FakeLLMClient("not valid json at all")
    fields = asyncio.run(extract_with_llm(transcript, fake))
    assert fields == extract(transcript)


def test_agent2_real_path_parses_llm_json():
    fake = _FakeLLMClient(
        '{"risk_level": "HIGH", "risk_score": 0.8, '
        '"drivers": [{"observation": "BP 140/90", "reason": "meets NHM pre-eclampsia threshold"}]}'
    )
    extracted = ExtractedFields(bp_systolic=140, bp_diastolic=90)
    result = asyncio.run(classify_with_llm(extracted, fake))
    assert result.risk_level == "HIGH"
    assert result.risk_score == 0.8
    assert len(result.drivers) == 1


def test_agent2_real_path_falls_back_to_rules_on_bad_json():
    extracted = ExtractedFields(bp_systolic=140, bp_diastolic=90, medication_compliance="non_compliant")
    fake = _FakeLLMClient("{not json")
    result = asyncio.run(classify_with_llm(extracted, fake))
    assert result.risk_level == classify(extracted).risk_level


def test_agent2_real_path_falls_back_on_invalid_risk_level():
    extracted = ExtractedFields(bp_systolic=110, bp_diastolic=70, medication_compliance="compliant")
    fake = _FakeLLMClient('{"risk_level": "SEVERE", "risk_score": 0.9, "drivers": []}')
    result = asyncio.run(classify_with_llm(extracted, fake))
    assert result.risk_level == classify(extracted).risk_level
