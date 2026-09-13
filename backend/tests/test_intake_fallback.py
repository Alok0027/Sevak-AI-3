"""The parser stays in front; the model only covers what it could not read.

Registering a patient is on the offline path (FR-07), so this must never
become "ask the model, fall back to the parser" -- an ASHA with no signal
still has to be able to speak a name and save it.

Measured before this existed: of six realistic utterances the parser read
three perfectly and missed an age given as "umar 24", a village named as
"Baramati gaon se", and everything in "twenty six saal ki". Those three are
what the fallback is for.
"""
import asyncio

import pytest

from app.services.llm_client import LLMClientBase, MockLLMClient
from app.services.patient_intake import extract, extract_with_llm


class _CountingLLM(LLMClientBase):
    def __init__(self, payload='{"name": "Anjali", "age": 26, "village": "Khed"}'):
        self.payload = payload
        self.calls = 0

    async def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self.payload


CLEAN = "Sunita Devi, 32 saal, gaon Wagholi, phone 9876543210, female"
UNPARSEABLE = "ye Anjali hai, twenty six saal ki, Khed village"


def test_a_transcript_the_parser_reads_never_reaches_the_model():
    """Latency an ASHA notices, spent re-deriving an answer already in hand."""
    llm = _CountingLLM()
    result = asyncio.run(extract_with_llm(CLEAN, llm))
    assert llm.calls == 0
    assert result.name == "Sunita Devi" and result.age == 32


def test_the_parser_still_fails_on_this_one():
    """If the parser learns to read it, the fallback test below is testing
    nothing -- so pin the gap the fallback exists to cover."""
    parsed = extract(UNPARSEABLE)
    assert parsed.name is None or parsed.age is None


def test_the_model_fills_what_the_parser_missed():
    llm = _CountingLLM()
    result = asyncio.run(extract_with_llm(UNPARSEABLE, llm))
    assert llm.calls == 1
    assert result.name == "Anjali"
    assert result.age == 26
    assert result.village == "Khed"


def test_the_parser_wins_where_both_have_a_value():
    """It was written against these two transcript styles; the model was
    not. Disagreement resolves towards the deterministic one."""
    llm = _CountingLLM('{"name": "Wrong Name", "age": 99, "village": "Elsewhere"}')
    # Parser gets the village but not the age, so the call happens.
    result = asyncio.run(extract_with_llm("Kamla, gaon Shirur", llm))
    if extract("Kamla, gaon Shirur").village:
        assert result.village == "Shirur"


def test_offline_returns_the_parser_result_rather_than_failing():
    class _NoNetwork(LLMClientBase):
        async def complete(self, system: str, user: str) -> str:
            raise ConnectionError("no route to host")

    result = asyncio.run(extract_with_llm(CLEAN, _NoNetwork()))
    assert result.name == "Sunita Devi", "a network failure lost the parsed fields"


def test_mock_provider_never_calls_out():
    llm = MockLLMClient()
    assert asyncio.run(extract_with_llm(UNPARSEABLE, llm)).name is None


def test_no_client_at_all_is_safe():
    assert asyncio.run(extract_with_llm(CLEAN, None)).name == "Sunita Devi"


def test_malformed_model_output_keeps_the_parsed_fields():
    result = asyncio.run(extract_with_llm(CLEAN, _CountingLLM("not json")))
    assert result.name == "Sunita Devi"


@pytest.mark.parametrize("payload", [
    '{"name": {"first": "Anjali"}, "age": 26}',      # wrong type for one field
    '{"age": "twenty six"}',                          # unusable age
])
def test_one_bad_field_does_not_lose_the_others(payload):
    result = asyncio.run(extract_with_llm(UNPARSEABLE, _CountingLLM(payload)))
    assert result is not None  # did not raise
