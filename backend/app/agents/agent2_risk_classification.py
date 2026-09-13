"""Agent 2 -- Risk Classification (FR-03).

Three entry points, in increasing order of how much they can explain:

    classify()            the NHM threshold engine alone
                          (app/services/nhm_protocol_rag.py). Deterministic,
                          offline, no network. The mock path, and the
                          fallback under both of the others.

    classify_with_llm()   LLM reasoning grounded on thresholds restated in
                          the prompt. Predates the corpus; kept because it
                          needs no retrieval.

    classify_with_rag()   retrieves the relevant NHM guidance from
                          ../nhm_corpus, reasons over the actual text, and
                          returns drivers that cite the document they came
                          from. This is what the pipeline calls (graph.py).

Each falls back to the one above it, so RETRIEVAL_PROVIDER=none or an
absent corpus returns this agent to exactly its earlier behaviour.

Two things hold whichever path runs. The threshold engine is a floor: the
final level is the higher of rules and model, so retrieval can escalate and
explain but never downgrade. And every HIGH flag still requires an ASHA
confirmation tap before escalating (FR-03.3), which is the SRS's own
documented mitigation for a misclassification any of these could produce."""
import json
import logging

from app.schemas.visit import ExtractedFields, RiskDriver
from app.services.llm_client import LLMClientBase, MockLLMClient
from app.services.nhm_protocol_rag import RiskResult, get_nhm_knowledge_base, has_clinical_signal
from app.core.config import get_settings
from app.services.nhm_retrieval import ProtocolChunk, retrieve

logger = logging.getLogger(__name__)


def classify(extracted: ExtractedFields) -> RiskResult:
    kb = get_nhm_knowledge_base()
    return kb.classify(extracted)


_RISK_SYSTEM_PROMPT = (
    "You are classifying maternal/child home-visit risk for an Indian ASHA "
    "community health worker, applying NHM (National Health Mission) "
    "protocol thresholds: BP >=140/90 is HIGH risk (pre-eclampsia threshold); "
    "BP >=130/85 (but below 140/90) is elevated/MEDIUM; a temperature "
    ">=38.0C during pregnancy requires prompt evaluation; non-compliant "
    "iron/medication course raises anaemia/complication risk; social risk "
    "factors (absent spouse, household isolation, economic stress) reduce "
    "the likelihood of timely facility follow-up and should raise risk; "
    "fasting blood sugar >=126 mg/dL or random >=200 mg/dL meets the "
    "diabetes threshold and is HIGH, while fasting 100-125 or random "
    "140-199 is elevated/MEDIUM. Any reported violence or injury (a "
    "non-empty violence_or_injury) is HIGH on its own, whatever the other "
    "readings show, because it needs same-day escalation. "
    "Respond with ONLY a raw JSON object (no markdown fences, no commentary): "
    "{\"risk_level\": \"HIGH\"|\"MEDIUM\"|\"LOW\", \"risk_score\": 0.0-1.0, "
    "\"drivers\": [{\"observation\": \"...\", \"reason\": \"...\"}]}. "
    "Every driver's reason must cite the specific NHM threshold it applies. "
    "If nothing abnormal was observed, return LOW with one driver noting "
    "normal findings."
)


async def classify_with_llm(extracted: ExtractedFields, llm_client: LLMClientBase) -> RiskResult:
    """FR-03 entry point used by the pipeline. Mock client -> identical
    rule-based `classify()` output. Real client -> LLM reasoning grounded
    on the NHM thresholds above, falling back to `classify()` on any
    failure to parse/validate its response (risk classification is
    safety-critical, so a malformed LLM reply must never leave a visit
    unclassified)."""
    if isinstance(llm_client, MockLLMClient):
        return classify(extracted)

    # Never ask the LLM to classify an empty record. Given a struct with
    # every clinical field null it does not answer "I cannot tell" -- it
    # answers LOW, fluently and with a reason, because the prompt above
    # tells it to return LOW when nothing abnormal was observed and it has
    # no way to distinguish "observed, normal" from "observed nothing".
    # That is precisely the failure this guard exists to stop, and it is
    # worse on the LLM path than the rule path because the answer arrives
    # with a confident justification attached.
    if not has_clinical_signal(extracted):
        return classify(extracted)

    try:
        observations = extracted.model_dump_json(exclude_none=True)
        raw = await llm_client.complete(_RISK_SYSTEM_PROMPT, observations)
        data = json.loads(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
        drivers = [RiskDriver(**d) for d in data["drivers"]]
        if not drivers:
            raise ValueError("LLM returned zero drivers")
        risk_level = data["risk_level"]
        if risk_level not in ("HIGH", "MEDIUM", "LOW"):
            raise ValueError(f"unexpected risk_level: {risk_level!r}")
        return RiskResult(risk_level=risk_level, risk_score=float(data["risk_score"]), drivers=drivers)
    except Exception:  # noqa: BLE001 -- any bad/malformed LLM response falls back, never leaves a visit unclassified
        return classify(extracted)


# ---------------------------------------------------------------------------
# FR-03.1: retrieval-grounded classification
# ---------------------------------------------------------------------------

_SEVERITY = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def build_query(extracted: ExtractedFields) -> str:
    """Turn the extracted record into the sentence a clinician would use.

    Not `model_dump_json()`. Retrieval matches words against a corpus
    written in prose, and `{"bp_systolic": 150}` shares no vocabulary with
    "If the BP is high (more than 140/90 mmHg)". Naming the concept --
    "blood pressure 150/100" -- is what makes the right passage findable.
    """
    parts: list[str] = []
    if extracted.bp_systolic and extracted.bp_diastolic:
        parts.append(f"blood pressure {extracted.bp_systolic}/{extracted.bp_diastolic} mmHg hypertension")
    if extracted.temperature_c:
        parts.append(f"temperature {extracted.temperature_c} C fever")
    if extracted.blood_sugar_fasting:
        parts.append(f"fasting blood sugar {extracted.blood_sugar_fasting} mg/dL glucose diabetes")
    if extracted.blood_sugar_random:
        parts.append(f"random blood sugar {extracted.blood_sugar_random} mg/dL glucose diabetes")
    if extracted.medication_compliance == "non_compliant":
        detail = extracted.medication_compliance_detail or "iron folic acid tablets"
        parts.append(f"not taking {detail} missed IFA anaemia haemoglobin")
    if extracted.violence_or_injury:
        parts.append(", ".join(extracted.violence_or_injury))
    if extracted.social_risk_factors:
        parts.append(", ".join(extracted.social_risk_factors))
    if extracted.pregnancy_stage:
        parts.append(f"{extracted.pregnancy_stage} pregnant antenatal")
    return "; ".join(parts)


def infer_phase(extracted: ExtractedFields) -> str | None:
    """Which stage of care the corpus should be read for.

    Only antenatal can be inferred today, from pregnancy_stage. Agent 1
    does not yet extract "delivered three days ago" or record that the
    subject is a newborn, so postnatal and newborn visits return None and
    search the whole corpus -- which is the safe direction: no hint means
    no demotion, so nothing is hidden.
    """
    return "antenatal" if extracted.pregnancy_stage else None


_RAG_SYSTEM_PROMPT = (
    "You are classifying maternal/child home-visit risk for an Indian ASHA "
    "community health worker. You are given extracts from India's National "
    "Health Mission (NHM) protocol documents and the observations from one "
    "home visit.\n\n"
    "Judge the risk USING ONLY the provided extracts. If the extracts do "
    "not cover an observation, say so in that driver's reason rather than "
    "reasoning from general medical knowledge -- the point of this system "
    "is that every judgement traces to a published Indian guideline.\n\n"
    "For each driver, set \"source_index\" to the number of the extract "
    "that justifies it, or null if no extract does.\n\n"
    "Respond with ONLY a raw JSON object, no markdown fences and no "
    "commentary: {\"risk_level\": \"HIGH\"|\"MEDIUM\"|\"LOW\", "
    "\"risk_score\": 0.0-1.0, \"drivers\": [{\"observation\": \"...\", "
    "\"reason\": \"...\", \"source_index\": 0}]}. "
    "Write each reason in one plain sentence an ASHA with a tenth-standard "
    "education can act on. Quote the threshold from the extract where there "
    "is one."
)


def _format_extracts(chunks: list[ProtocolChunk]) -> str:
    return "\n\n".join(
        f"[{i}] {c.title} — {c.heading}\n{c.text}" for i, c in enumerate(chunks)
    )


async def classify_with_rag(extracted: ExtractedFields, llm_client: LLMClientBase) -> RiskResult:
    """FR-03.1/03.2: risk classified against retrieved NHM guidance.

    The deterministic thresholds are not replaced by this -- they are the
    floor underneath it. The final level is the higher of what the rules
    say and what the LLM says, so retrieval can add explanation and can
    escalate, and cannot downgrade. A patient at 160/110 is HIGH whether or
    not the search found the right page, whether or not the LLM read it
    properly, and whether or not the corpus happens to cover her.

    That asymmetry is deliberate and it is the whole safety argument. The
    failure modes of retrieval -- an empty corpus, a bad query, a model
    having an off day -- all produce *less* alarming answers, and this is a
    system where the cost of missing a pre-eclamptic patient is not
    symmetric with the cost of an unnecessary referral.
    """
    floor = classify(extracted)

    # Nothing to classify, or nothing to classify it with.
    if floor.risk_level == "UNASSESSED" or isinstance(llm_client, MockLLMClient):
        return floor

    query = build_query(extracted)
    chunks = retrieve(query, k=get_settings().retrieval_top_k, phase=infer_phase(extracted))
    if not chunks:
        # No corpus, no match, or retrieval is switched off. The thresholds
        # already classified her; they just cannot cite anything.
        return floor

    try:
        raw = await llm_client.complete(
            _RAG_SYSTEM_PROMPT,
            f"NHM PROTOCOL EXTRACTS:\n{_format_extracts(chunks)}\n\n"
            f"HOME VISIT OBSERVATIONS:\n{extracted.model_dump_json(exclude_none=True)}",
        )
        data = json.loads(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
        level = data["risk_level"]
        if level not in _SEVERITY:
            raise ValueError(f"unexpected risk_level: {level!r}")

        drivers: list[RiskDriver] = []
        for d in data["drivers"]:
            idx = d.get("source_index")
            # Validated, not trusted. A model that invents index 7 against
            # three extracts would otherwise produce a driver citing a
            # document that was never retrieved -- a fabricated citation,
            # which is worse than none because it survives review.
            chunk = chunks[idx] if isinstance(idx, int) and 0 <= idx < len(chunks) else None
            drivers.append(RiskDriver(
                observation=d["observation"],
                reason=d["reason"],
                source=chunk.citation if chunk else None,
                source_url=chunk.source_url if chunk else None,
            ))
        if not drivers:
            raise ValueError("LLM returned zero drivers")
    except Exception:  # noqa: BLE001 -- any failure lands on the thresholds
        logger.warning("RAG classification failed; using threshold result", exc_info=True)
        return floor

    if _SEVERITY[level] < _SEVERITY[floor.risk_level]:
        # The floor wins, but the retrieved reasoning is still worth
        # keeping: it explains the observations, it just did not outrank
        # the rule that fired. Merged rather than discarded so the ASHA
        # sees both why the system escalated and what the guideline says.
        logger.info("RAG said %s, thresholds said %s; keeping %s",
                    level, floor.risk_level, floor.risk_level)
        return RiskResult(
            risk_level=floor.risk_level,
            risk_score=max(floor.risk_score, float(data.get("risk_score", 0.0))),
            drivers=floor.drivers + drivers,
        )

    return RiskResult(
        risk_level=level,
        risk_score=max(float(data["risk_score"]), floor.risk_score),
        drivers=drivers,
    )
