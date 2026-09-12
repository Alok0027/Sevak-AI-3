"""
Voice-driven patient registration -- lets an ASHA worker speak a new
patient's basic details instead of typing them into the Add Patient form.

Parses both scripts, because two different transcript styles reach this
function: the mock STT replays romanized Hinglish ("Sunita Devi, 32 saal,
gaon Wagholi"), while real Bhashini returns Devanagari with no punctuation
at all and numbers written as words ("सुंदर देवी उम्र बत्तीस साल महिला
गांव वघोली फ़ोन नंबर एक दो तीन चार...").

That second shape is why name and village are read by walking tokens
rather than by regex: a pattern that ends a name at a comma or danda
never terminates on Bhashini output, and silently matches nothing. Here a
field simply runs until the next word that can't belong to it.

This is *not* the clinical extractor -- it pulls the registration fields
app.schemas.patient.PatientCreate needs, plus a baseline BP/blood sugar,
and is deliberately separate from agent1 so clinical-visit extraction and
patient-registration extraction can evolve independently.

TODO (real mode): once LLM_API_KEY is set, swap extract()'s body for an
LLM call the same way agent1's docstring describes -- keep this function's
signature so nothing downstream needs to change.

Every extracted field is a *suggestion*: the mobile app always shows it in
an editable form before the ASHA taps Save (FR-01.4-style review step), so
a wrong guess here is a minor annoyance, never silently-wrong data.
"""
import re

from app.schemas.patient import ExtractedIntakeFields
from app.services.hindi_numbers import parse_number, spoken_digits_to_phone
from app.services.vitals_parsing import find_blood_sugar, find_bp

_AGE_UNITS = {"saal", "years", "year", "yrs", "yr", "साल", "बरस", "वर्ष"}
_MONTH_UNITS = {"mahine", "mahina", "month", "months", "महीने", "महीना", "माह"}
_NAME_ANCHORS = {"naam", "name", "नाम"}
_VILLAGE_ANCHORS = {"village", "gaon", "gaanv", "gram", "गाँव", "गांव", "गाव", "ग्राम"}

# Words that can never be part of a name or a village name, so they mark
# where one ends. With no punctuation in the transcript this is the only
# boundary available.
_BOUNDARY_WORDS = (
    _AGE_UNITS
    | _MONTH_UNITS
    | _NAME_ANCHORS
    | _VILLAGE_ANCHORS
    | {
        "umar", "umr", "age", "उम्र", "उमर", "आयु",
        "female", "male", "mahila", "aurat", "purush", "mard",
        "महिला", "औरत", "स्त्री", "लड़की", "पुरुष", "आदमी", "मर्द", "लड़का",
        "phone", "mobile", "number", "फ़ोन", "फोन", "मोबाइल", "नंबर", "नम्बर",
        "pregnant", "pregnancy", "प्रेग्नेंट", "गर्भवती", "गर्भ",
        "pati", "husband", "पति", "पत्नी",
        "bp", "बीपी", "sugar", "शुगर", "शक्कर",
        "hai", "hain", "mein", "me", "se", "ka", "ki", "ke", "rehti", "rehta",
        "है", "हैं", "में", "से", "का", "की", "के", "को", "और", "पर",
    }
)

_TOKEN_RE = re.compile(r"[^\s,.।]+")
_PHONE_DIGITS_RE = re.compile(r"(\d[\d\s-]{8,13}\d)")
_FEMALE_RE = re.compile(r"\bfemale\b|\bmahila\b|\baurat\b|महिला|औरत|स्त्री|लड़की", re.IGNORECASE)
_MALE_RE = re.compile(r"\bmale\b|\bpurush\b|\bmard\b|पुरुष|आदमी|मर्द|लड़का", re.IGNORECASE)

_MAX_NAME_WORDS = 5
_MAX_VILLAGE_WORDS = 3


def _tokens(transcript: str) -> list[str]:
    return _TOKEN_RE.findall(transcript)


def _is_boundary(token: str) -> bool:
    """True at the first word that cannot belong to a name or village --
    a keyword, or any number (spoken or written)."""
    return token.lower() in _BOUNDARY_WORDS or parse_number(token) is not None


def _take_until_boundary(tokens: list[str], start: int, limit: int) -> str | None:
    taken: list[str] = []
    for token in tokens[start : start + limit]:
        if _is_boundary(token):
            break
        taken.append(token)
    return " ".join(taken) if taken else None


def _find_anchor(tokens: list[str], anchors: set[str]) -> int | None:
    for i, token in enumerate(tokens):
        if token.lower() in anchors:
            return i
    return None


def _value_before_unit(tokens: list[str], units: set[str]) -> int | None:
    """The number immediately preceding a unit word -- "बत्तीस साल" -> 32,
    "32 saal" -> 32, "छ महीना" -> 6."""
    for i, token in enumerate(tokens):
        if token.lower() in units and i > 0:
            if (value := parse_number(tokens[i - 1])) is not None:
                return value
    return None


def extract(transcript: str) -> ExtractedIntakeFields:
    fields = ExtractedIntakeFields()
    confidence: dict[str, float] = {}
    tokens = _tokens(transcript)

    # An explicit "naam"/"नाम" is evidence enough on its own.
    anchor = _find_anchor(tokens, _NAME_ANCHORS)
    if anchor is not None:
        if name := _take_until_boundary(tokens, anchor + 1, _MAX_NAME_WORDS):
            fields.name = name
            confidence["name"] = 0.8

    if (age := _value_before_unit(tokens, _AGE_UNITS)) is not None:
        fields.age = age
        confidence["age"] = 0.9

    village_at = _find_anchor(tokens, _VILLAGE_ANCHORS)
    if village_at is not None:
        if village := _take_until_boundary(tokens, village_at + 1, _MAX_VILLAGE_WORDS):
            fields.village = village
            confidence["village"] = 0.8

    if (months := _value_before_unit(tokens, _MONTH_UNITS)) is not None:
        fields.pregnancy_stage = f"{months} months"
        confidence["pregnancy_stage"] = 0.85

    # Dictated as digits ("98765 43210") or spoken one at a time
    # ("एक दो तीन चार..."), which is how it actually comes back from ASR.
    if m := _PHONE_DIGITS_RE.search(transcript):
        digits = re.sub(r"\D", "", m.group(1))
        if len(digits) == 10:
            fields.phone = digits
            confidence["phone"] = 0.9
    if fields.phone is None:
        if spoken := spoken_digits_to_phone(transcript):
            fields.phone = spoken
            confidence["phone"] = 0.8

    if _FEMALE_RE.search(transcript):
        fields.gender = "female"
        confidence["gender"] = 0.85
    elif _MALE_RE.search(transcript):
        fields.gender = "male"
        confidence["gender"] = 0.85

    # Baseline vitals, if she happened to state them while registering.
    if bp := find_bp(transcript):
        fields.bp_systolic, fields.bp_diastolic = bp
        confidence["bp_systolic"] = 0.9
        confidence["bp_diastolic"] = 0.9
    fasting, random_sugar = find_blood_sugar(transcript)
    if fasting is not None:
        fields.blood_sugar_fasting = fasting
        confidence["blood_sugar_fasting"] = 0.85
    if random_sugar is not None:
        fields.blood_sugar_random = random_sugar
        confidence["blood_sugar_random"] = 0.85

    # ASHAs lead with the patient's name ("सुंदर देवी उम्र बत्तीस साल"),
    # so with no explicit "naam" the opening words are the best guess --
    # but only once something else has confirmed this is a patient
    # description at all. Ungated, the same rule reads the first few words
    # of any passing remark as somebody's name.
    if fields.name is None and confidence:
        if name := _take_until_boundary(tokens, 0, _MAX_NAME_WORDS):
            fields.name = name
            confidence["name"] = 0.7

    fields.confidence_scores = confidence
    return fields
