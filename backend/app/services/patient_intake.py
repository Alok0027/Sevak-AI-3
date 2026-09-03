"""
Voice-driven patient registration -- lets an ASHA worker speak a new
patient's basic details instead of typing them into the Add Patient form.

Mirrors app/agents/agent1_voice_comprehension.py's approach on purpose:
a deterministic, regex-based parser tuned to the same Hinglish phrasing
ASHA workers use in the field ("Meera Patil, 28 saal", "gaon Wagholi",
"mobile number 98765 43210"), with zero external calls. This is *not* the
clinical extractor -- it only pulls the five registration fields
(name/age/gender/village/phone) that app.schemas.patient.PatientCreate
needs, and is deliberately separate from agent1 so clinical-visit
extraction and patient-registration extraction can evolve independently.

TODO (real mode): once LLM_API_KEY is set, swap extract()'s body for an
LLM call the same way agent1's docstring describes -- keep this function's
signature so nothing downstream needs to change.

Every extracted field is a *suggestion*: the mobile app always shows it in
an editable form before the ASHA taps Save (FR-01.4-style review step), so
a wrong guess here is a minor annoyance, never silently-wrong data.
"""
import re

from app.schemas.patient import ExtractedIntakeFields

# Same "Name, age saal" shape the clinical extractor already handles well
# for natural ASHA-worker phrasing (see agent1_voice_comprehension.py).
_NAME_AGE_RE = re.compile(r"([A-Za-zऀ-ॿ][A-Za-zऀ-ॿ .]*?),?\s*(\d{1,3})\s*(?:saal|years?|yrs?)", re.IGNORECASE)
# Fallback if age wasn't spoken right after the name: "naam X hai" / "name is X".
_NAME_ONLY_RE = re.compile(
    r"(?:naam|name)\s+(?:is\s+|hai\s+)?([A-Za-zऀ-ॿ][A-Za-zऀ-ॿ .]{1,40}?)(?:,|\.|\s+(?:hai|umar|umr|age|saal)|$)",
    re.IGNORECASE,
)
_AGE_RE = re.compile(r"(\d{1,3})\s*(?:saal|years?|yrs?|year[- ]old)", re.IGNORECASE)
_VILLAGE_RE = re.compile(
    r"(?:village|gaon|gaanv|gram)\s+(?:is\s+|hai\s+|mein\s+)?([A-Za-zऀ-ॿ][A-Za-zऀ-ॿ ]{1,30}?)"
    r"(?:,|\.|\s+(?:district|tehsil|state|mein|se|hai)|$)",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"(\d[\d\s-]{8,13}\d)")
_FEMALE_RE = re.compile(r"\bfemale\b|\bmahila\b|\baurat\b", re.IGNORECASE)
_MALE_RE = re.compile(r"\bmale\b|\bpurush\b|\bmard\b", re.IGNORECASE)

# _NAME_AGE_RE is deliberately permissive (any word before "N saal") so it
# catches natural phrasing like "Meera Patil, 28 saal" -- but that means it
# can also latch onto the Hindi/English word for "age" itself when age is
# spoken as its own clause ("umar 45 saal" rather than "Name, 45 saal").
# Reject those before trusting the match as a name.
_NAME_STOPWORDS = {"umar", "umr", "age", "naam", "name"}


def extract(transcript: str) -> ExtractedIntakeFields:
    fields = ExtractedIntakeFields()
    confidence: dict[str, float] = {}

    if m := _NAME_AGE_RE.search(transcript):
        candidate = m.group(1).strip().rstrip(",")
        if candidate.lower() not in _NAME_STOPWORDS:
            fields.name = candidate
            confidence["name"] = 0.85
            fields.age = int(m.group(2))
            confidence["age"] = 0.95

    if fields.name is None:
        if m := _NAME_ONLY_RE.search(transcript):
            candidate = m.group(1).strip().rstrip(",")
            if candidate.lower() not in _NAME_STOPWORDS:
                fields.name = candidate
                confidence["name"] = 0.7

    if fields.age is None:
        if m := _AGE_RE.search(transcript):
            fields.age = int(m.group(1))
            confidence["age"] = 0.9

    if m := _VILLAGE_RE.search(transcript):
        fields.village = m.group(1).strip().rstrip(",")
        confidence["village"] = 0.8

    if m := _PHONE_RE.search(transcript):
        digits = re.sub(r"\D", "", m.group(1))
        if len(digits) == 10:
            fields.phone = digits
            confidence["phone"] = 0.9

    if _FEMALE_RE.search(transcript):
        fields.gender = "female"
        confidence["gender"] = 0.85
    elif _MALE_RE.search(transcript):
        fields.gender = "male"
        confidence["gender"] = 0.85

    fields.confidence_scores = confidence
    return fields
