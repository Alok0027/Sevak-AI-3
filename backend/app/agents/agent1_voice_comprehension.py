"""
Agent 1 -- Voice Comprehension & Entity Extraction (FR-02).

Takes the Bhashini transcript and pulls out: patient identity, clinical
vitals, medication compliance, and social risk factors, then emits the
structured JSON record FR-02.5 requires.

The extractor below is a deterministic, regex-based parser tuned to the
Hinglish phrasing used in the SRS's own demo script (section 9.1) and
common ASHA-worker speech patterns ("28 saal", "BP 140 over 90", "iron
tablets nahi li", "pati bahar gaya hua hai"). It runs with zero external
calls, which is what makes `USE_MOCKS=true` fully offline.

TODO (real mode): once LLM_API_KEY is set, replace `extract()`'s body with
a call to app.services.llm_client's LLMClient.complete() using a clinical
NER system prompt in JSON-mode, and keep this same function signature so
nothing downstream needs to change. Keep the regex path as a fast local
fallback for when the LLM call fails or is rate-limited (see FR-01.3 /
NFR-P1 -- the pipeline must not silently hang if a call stalls).
"""
import re

from app.schemas.visit import ExtractedFields

_NAME_AGE_RE = re.compile(r"([A-Za-zऀ-ॿ][A-Za-zऀ-ॿ .]*?),?\s*(\d{1,3})\s*(?:saal|years?|yrs?)", re.IGNORECASE)
_PREGNANCY_RE = re.compile(r"(\d{1,2})\s*(?:mahine|month)s?", re.IGNORECASE)
_BP_RE = re.compile(r"BP\s*(\d{2,3})\s*(?:over|/|-)\s*(\d{2,3})", re.IGNORECASE)
_TEMP_RE = re.compile(r"(?:temperature|bukhar|fever)\D{0,12}(\d{2,3}(?:\.\d)?)", re.IGNORECASE)
_WEIGHT_RE = re.compile(r"(\d{2,3}(?:\.\d)?)\s*(?:kg|kilo)", re.IGNORECASE)
_DURATION_RE = re.compile(r"(pichle|last)\s*(\d+)\s*(hafte|din|week|day)s?", re.IGNORECASE)

_MED_KEYWORDS = ["iron tablet", "tablet", "medicine", "dawai", "dawaai"]
_NON_COMPLIANCE_MARKERS = ["nahi li", "nahi liya", "not taken", "skipped", "missed"]

_SOCIAL_RISK_RULES = [
    (re.compile(r"pati\s+bahar|husband\s+(is\s+)?(away|absent)", re.IGNORECASE), "absent spouse"),
    (re.compile(r"akel[ai]|isolated|alone at home", re.IGNORECASE), "household isolation"),
    (re.compile(r"paisa\s*nahi|no money|can'?t afford|gareeb", re.IGNORECASE), "economic stress"),
]


def extract(transcript: str) -> ExtractedFields:
    fields = ExtractedFields()
    confidence: dict[str, float] = {}

    if m := _NAME_AGE_RE.search(transcript):
        fields.patient_name = m.group(1).strip().rstrip(",")
        fields.age = int(m.group(2))
        confidence["patient_name"] = 0.9
        confidence["age"] = 0.95

    if m := _PREGNANCY_RE.search(transcript):
        fields.pregnancy_stage = f"{m.group(1)} months"
        confidence["pregnancy_stage"] = 0.9

    if m := _BP_RE.search(transcript):
        fields.bp_systolic = int(m.group(1))
        fields.bp_diastolic = int(m.group(2))
        confidence["bp_systolic"] = 0.95
        confidence["bp_diastolic"] = 0.95

    if m := _TEMP_RE.search(transcript):
        fields.temperature_c = float(m.group(1))
        confidence["temperature_c"] = 0.85

    if m := _WEIGHT_RE.search(transcript):
        fields.weight_kg = float(m.group(1))
        confidence["weight_kg"] = 0.85

    lowered = transcript.lower()
    mentioned_med = next((kw for kw in _MED_KEYWORDS if kw in lowered), None)
    if mentioned_med:
        non_compliant = any(marker in lowered for marker in _NON_COMPLIANCE_MARKERS)
        fields.medication_compliance = "non_compliant" if non_compliant else "compliant"
        duration = ""
        if d := _DURATION_RE.search(transcript):
            duration = f" for {d.group(2)} {d.group(3)}"
        fields.medication_compliance_detail = f"{mentioned_med}{duration}".strip()
        confidence["medication_compliance"] = 0.85
    else:
        fields.medication_compliance = "unknown"

    social_risks = []
    for pattern, label in _SOCIAL_RISK_RULES:
        if pattern.search(transcript):
            social_risks.append(label)
    fields.social_risk_factors = social_risks
    if social_risks:
        confidence["social_risk_factors"] = 0.8

    fields.confidence_scores = confidence
    return fields
