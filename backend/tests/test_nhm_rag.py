"""Retrieval over the NHM corpus, and the floor underneath it.

The safety argument for grounding risk classification in a retrieved
document is only as good as what happens when retrieval is wrong. These
tests are mostly about that: an empty corpus, a bad match, a model that
answers LOW for a woman at 170/115, a model that cites a document it was
never shown. None of those may be allowed to make a patient look safer
than the thresholds already say she is.
"""
import asyncio
import json
from pathlib import Path

import pytest

from app.agents import agent2_risk_classification as agent2
from app.agents.agent2_risk_classification import build_query, classify_with_rag, infer_phase
from app.schemas.visit import ExtractedFields
from app.services.llm_client import LLMClientBase
from app.services.nhm_retrieval import (
    CORPUS_DIR,
    LexicalRetriever,
    NullRetriever,
    load_corpus,
    tokenise,
)


# --------------------------------------------------------------------------
# The corpus itself
# --------------------------------------------------------------------------

def test_corpus_loads_with_provenance_on_every_chunk():
    chunks = load_corpus()
    assert chunks, "corpus is empty; retrieval would silently do nothing"
    for c in chunks:
        assert c.title, f"{c.doc_id} chunk has no document title"
        assert c.source_url.startswith("http"), f"{c.doc_id} has no source URL"
        assert c.publisher, f"{c.doc_id} names no publisher"
        assert c.text.strip()


def test_every_corpus_document_is_traceable_to_a_government_source():
    """A citation is only worth showing if it points somewhere real. This
    does not verify the URL resolves -- that would make the suite depend on
    the network and on nhm.gov.in being up -- but it does stop a document
    being added with an invented or missing origin."""
    for c in load_corpus():
        assert ".gov.in" in c.source_url or ".nic.in" in c.source_url, (
            f"{c.doc_id} cites {c.source_url!r}, which is not a government domain"
        )


def test_readme_is_not_retrievable():
    assert not any(c.doc_id.lower() == "readme" for c in load_corpus())


def test_thresholds_survive_tokenisation():
    """"140/90" and "10.9" are the most discriminating tokens in the corpus.
    A tokeniser that splits them into "140", "90" loses exactly the terms
    that tell one guideline apart from another."""
    assert "140/90" in tokenise("BP more than 140/90 mmHg")
    assert "10.9" in tokenise("mild anaemia 10-10.9 g/dl")


# --------------------------------------------------------------------------
# Retrieval quality
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def retriever():
    return LexicalRetriever(load_corpus())


@pytest.mark.parametrize("query, expected_doc", [
    ("blood pressure 160/110 severe headache blurred vision", "antenatal_care"),
    ("haemoglobin 6.4 g/dL pale and giddy", "anaemia_in_pregnancy"),
    ("random blood sugar 210 mg/dL glucose", "gestational_diabetes"),
    ("newborn breathing fast not feeding 3 days old", "newborn_home_care"),
    ("soaking 3 pads in 20 minutes after delivery", "postnatal_care"),
])
def test_clinical_queries_reach_the_right_document(retriever, query, expected_doc):
    hits = retriever.search(query, k=3)
    assert hits, f"nothing retrieved for {query!r}"
    assert expected_doc in {c.doc_id for c, _ in hits}, (
        f"{query!r} retrieved {[c.doc_id for c, _ in hits]}, expected {expected_doc}"
    )


def test_phase_hint_keeps_an_antenatal_case_out_of_postnatal_guidance():
    """The failure this was built for. "Swelling on face, hands and legs"
    appears verbatim in both the antenatal and postnatal danger-sign lists,
    and the postnatal list is longer, so a seven-months-pregnant woman with
    a high BP and facial swelling retrieved postnatal guidance above the
    antenatal blood-pressure thresholds -- right concern, wrong stage."""
    r = LexicalRetriever(load_corpus())
    q = "blood pressure 150/100 swelling of face and hands, 7 months pregnant"

    unhinted = r.search(q, k=1)[0][0]
    assert unhinted.phase == "postnatal", (
        "the bug this guards against is gone from the corpus; "
        "re-check whether the phase demotion is still needed"
    )

    hinted = r.search(q, k=1, phase="antenatal")[0][0]
    assert hinted.phase == "antenatal"
    assert "blood pressure" in hinted.heading.lower()


def test_phase_demotes_rather_than_excludes():
    """A postnatal chunk must still be reachable for an antenatal query --
    a woman whose record says "9 months" may have delivered yesterday."""
    r = LexicalRetriever(load_corpus())
    hits = r.search("heavy bleeding soaking pads convulsions", k=6, phase="antenatal")
    assert any(c.phase == "postnatal" for c, _ in hits)


def test_nonsense_query_retrieves_nothing_rather_than_the_longest_chunk():
    r = LexicalRetriever(load_corpus())
    assert r.search("xylophone quarterly shareholder meeting", k=3) == []


def test_query_is_built_in_the_corpus_vocabulary():
    """Retrieval matches words. A JSON dump of the record shares no
    vocabulary with prose guidance, so the observations have to be named
    the way the guideline names them."""
    q = build_query(ExtractedFields(bp_systolic=150, bp_diastolic=100, pregnancy_stage="7 months"))
    assert "150/100" in q
    assert "blood pressure" in q.lower()


def test_phase_is_inferred_only_when_known():
    assert infer_phase(ExtractedFields(pregnancy_stage="7 months")) == "antenatal"
    assert infer_phase(ExtractedFields(bp_systolic=120, bp_diastolic=80)) is None


# --------------------------------------------------------------------------
# The safety floor
# --------------------------------------------------------------------------

class _ScriptedLLM(LLMClientBase):
    def __init__(self, payload):
        self.payload = payload
        self.prompts: list[str] = []

    async def complete(self, system: str, user: str) -> str:
        self.prompts.append(user)
        return self.payload if isinstance(self.payload, str) else json.dumps(self.payload)


HIGH_RISK = ExtractedFields(bp_systolic=170, bp_diastolic=115, pregnancy_stage="8 months")


def test_the_llm_cannot_downgrade_a_high_risk_patient():
    """The whole safety argument. A woman at 170/115 is in imminent-eclampsia
    territory by NHM's own threshold; no amount of retrieved text or model
    confidence may make her look LOW."""
    llm = _ScriptedLLM({
        "risk_level": "LOW", "risk_score": 0.0,
        "drivers": [{"observation": "BP 170/115", "reason": "Looks fine.", "source_index": 0}],
    })
    result = asyncio.run(classify_with_rag(HIGH_RISK, llm))
    assert result.risk_level == "HIGH"


def test_a_downgrade_attempt_keeps_the_threshold_driver_too():
    llm = _ScriptedLLM({
        "risk_level": "LOW", "risk_score": 0.0,
        "drivers": [{"observation": "BP 170/115", "reason": "Looks fine.", "source_index": 0}],
    })
    result = asyncio.run(classify_with_rag(HIGH_RISK, llm))
    assert any("140/90" in d.reason or "pre-eclampsia" in d.reason.lower() for d in result.drivers), (
        "the rule that forced HIGH is not visible to the ASHA"
    )


def test_the_llm_may_escalate():
    """The floor is one-directional. Retrieved guidance finding something
    the thresholds do not encode should still be able to raise the level."""
    mild = ExtractedFields(bp_systolic=118, bp_diastolic=76, pregnancy_stage="6 months")
    llm = _ScriptedLLM({
        "risk_level": "HIGH", "risk_score": 0.9,
        "drivers": [{"observation": "Reported convulsion", "reason": "Immediate referral.", "source_index": 0}],
    })
    assert asyncio.run(classify_with_rag(mild, llm)).risk_level == "HIGH"


def test_malformed_llm_output_falls_back_to_thresholds():
    for payload in ("not json at all", {"risk_level": "CATASTROPHIC", "risk_score": 1.0, "drivers": []},
                    {"risk_level": "HIGH", "risk_score": 0.9, "drivers": []}):
        result = asyncio.run(classify_with_rag(HIGH_RISK, _ScriptedLLM(payload)))
        assert result.risk_level == "HIGH", f"fallback failed for {payload!r}"


def test_a_fabricated_citation_index_is_dropped_not_shown():
    """A model citing extract 7 when it was shown three would otherwise
    produce a driver pointing at a document that was never retrieved --
    worse than an uncited driver, because it survives review."""
    llm = _ScriptedLLM({
        "risk_level": "HIGH", "risk_score": 0.9,
        "drivers": [{"observation": "BP 170/115", "reason": "Refer.", "source_index": 7}],
    })
    result = asyncio.run(classify_with_rag(HIGH_RISK, llm))
    assert all(d.source is None or d.source_url for d in result.drivers)
    cited = [d for d in result.drivers if d.source]
    assert not any(d.source and "7" == d.source for d in cited)


def test_a_valid_citation_reaches_the_driver():
    llm = _ScriptedLLM({
        "risk_level": "HIGH", "risk_score": 0.9,
        "drivers": [{"observation": "BP 170/115", "reason": "Refer immediately.", "source_index": 0}],
    })
    result = asyncio.run(classify_with_rag(HIGH_RISK, llm))
    cited = [d for d in result.drivers if d.source]
    assert cited, "no driver carried a citation"
    assert cited[0].source_url.startswith("http")
    assert any(c.citation == cited[0].source for c in load_corpus())


def test_the_extracts_actually_reach_the_prompt():
    """Otherwise this is an LLM call with a corpus-shaped decoration."""
    llm = _ScriptedLLM({
        "risk_level": "HIGH", "risk_score": 0.9,
        "drivers": [{"observation": "BP 170/115", "reason": "Refer.", "source_index": 0}],
    })
    asyncio.run(classify_with_rag(HIGH_RISK, llm))
    assert "NHM PROTOCOL EXTRACTS" in llm.prompts[0]
    assert "140/90" in llm.prompts[0], "the retrieved threshold is not in the prompt"


def test_no_retrieval_still_classifies(monkeypatch):
    """Corpus missing, retrieval off, or nothing matched: the thresholds
    classified her already. They just cannot cite anything."""
    monkeypatch.setattr(agent2, "retrieve", lambda *a, **k: [])
    llm = _ScriptedLLM({"risk_level": "LOW", "risk_score": 0.0, "drivers": []})
    result = asyncio.run(classify_with_rag(HIGH_RISK, llm))
    assert result.risk_level == "HIGH"
    assert not llm.prompts, "the LLM was called with no extracts to ground it"


def test_null_retriever_returns_nothing_without_raising():
    assert NullRetriever().search("blood pressure", k=3) == []


def test_corpus_directory_is_where_the_code_looks():
    assert CORPUS_DIR.is_dir(), f"{CORPUS_DIR} does not exist"
    assert any(CORPUS_DIR.glob("*.md"))


# --------------------------------------------------------------------------
# Citations reaching the dashboard
# --------------------------------------------------------------------------

def test_citations_are_extracted_and_deduplicated_from_stored_drivers():
    """Agent 5 builds the escalation payload from drivers_json. A citation
    that does not survive that step is computed, persisted and invisible --
    which is the state this whole feature exists to leave behind.

    Deduplicated because two drivers grounded on the same guideline section
    are one source; listing it twice reads as two independent confirmations.
    """
    import json as _json

    stored = _json.dumps([
        {"observation": "BP 170/115", "reason": "Above 140/90.",
         "source": "ANC Guidelines — Blood pressure thresholds in pregnancy",
         "source_url": "https://nhmmeghalaya.nic.in/guidelines/gfac.pdf"},
        {"observation": "Severe headache", "reason": "Danger sign.",
         "source": "ANC Guidelines — Blood pressure thresholds in pregnancy",
         "source_url": "https://nhmmeghalaya.nic.in/guidelines/gfac.pdf"},
        {"observation": "Missed iron", "reason": "Threshold engine.", "source": None},
    ])

    # Mirrors the block in agent5_escalation.build_escalations.
    parsed = _json.loads(stored)
    drivers = [d.get("reason", "") for d in parsed]
    seen, citations = set(), []
    for d in parsed:
        label = d.get("source")
        if label and label not in seen:
            seen.add(label)
            citations.append({"label": label, "url": d.get("source_url") or ""})

    assert len(drivers) == 3
    assert len(citations) == 1, "the two drivers sharing a source produced two citations"
    assert citations[0]["url"].startswith("http")


def test_a_threshold_only_flag_carries_no_citations():
    """Empty must mean "no citation available", not "unsourced and
    therefore suspect" -- every flag raised before the corpus existed is
    in this state and is perfectly valid."""
    from app.services.nhm_protocol_rag import get_nhm_knowledge_base

    result = get_nhm_knowledge_base().classify(
        ExtractedFields(bp_systolic=170, bp_diastolic=115)
    )
    assert result.risk_level == "HIGH"
    assert all(d.source is None for d in result.drivers)
