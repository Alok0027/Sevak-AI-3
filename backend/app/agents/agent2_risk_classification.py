"""Agent 2 -- Risk Classification (FR-03). `classify()` is the rule-based
NHM threshold engine (see app/services/nhm_protocol_rag.py); it's also the
mock/offline path and the fallback used by `classify_with_llm()` below,
which is what the pipeline actually calls (graph.py).

`classify_with_llm()` grounds the real LLM call with the same NHM
thresholds `classify()` encodes, rather than a real ChromaDB retrieval --
that's still the TODO in nhm_protocol_rag.py's docstring. Every HIGH flag
still requires an ASHA confirmation tap before escalating (FR-03.3), which
is the SRS's own documented mitigation for a misclassification either path
could produce."""
import json

from app.schemas.visit import ExtractedFields, RiskDriver
from app.services.llm_client import LLMClientBase, MockLLMClient
from app.services.nhm_protocol_rag import RiskResult, get_nhm_knowledge_base


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
