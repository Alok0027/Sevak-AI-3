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

`extract()` stays rule-based, and that is not a placeholder for an LLM
call. Registering a patient is on the offline path (FR-07): an ASHA
standing in a house with no signal must still be able to speak a name and
save it. An API call here would break exactly the situation this app
exists for, and the fields it recovers -- a name, an age, a village -- are
structured enough that a parser is more predictable than a model.

What it is not good at is phrasing it was not built for. Measured against
six realistic utterances it read three perfectly, including Devanagari with
the phone number spoken digit by digit, and on the other three it missed an
age given as "umar 24" (no unit word), a village named as "Baramati gaon
se" (anchor used as a suffix), and everything in "twenty six saal ki"
(an English number word). `extract_with_llm()` below covers that gap
without giving up the offline path.

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


async def extract_with_llm(transcript: str, llm_client) -> ExtractedIntakeFields:
    """The parser first; a model only for what it could not read.

    Deliberately not "ask the LLM, fall back to the parser". The parser is
    deterministic, instant and works with no signal, and on the transcript
    shapes it was built for it is already right -- spending a network call
    to re-derive an answer it has costs latency an ASHA notices and can
    only introduce disagreement.

    So: parse, and if the essentials came back, stop. Only a transcript the
    parser could not read is worth a model, and even then the parser's
    values win on merge, because it was written against these two specific
    transcript styles and the model was not.

    Every failure returns the parser's result, including no network at all.
    The worst case is the behaviour that existed before this function.
    """
    import json
    import logging

    from app.services.llm_client import MockLLMClient

    logger = logging.getLogger(__name__)
    fields = extract(transcript)

    # The two fields the Add Patient form cannot be saved without. If the
    # parser found both, it understood the sentence; anything else missing
    # is a blank the ASHA fills in faster than a round trip.
    if (fields.name and fields.age) or isinstance(llm_client, MockLLMClient) or llm_client is None:
        return fields

    try:
        raw = await llm_client.complete(
            "Extract patient registration details from an Indian ASHA worker's "
            "spoken description. The text may be Hindi in Devanagari, romanised "
            "Hinglish, or English, and numbers may be written as words in any of "
            "them. Return ONLY a raw JSON object, no markdown fences: "
            '{"name": str|null, "age": int|null, "gender": "female"|"male"|null, '
            '"village": str|null, "phone": str|null, "pregnancy_stage": str|null}. '
            "Use null for anything not stated. Do not translate or transliterate "
            "a name or a village -- return them in the script they were spoken in, "
            "because they are copied into a medical record.",
            transcript,
        )
        data = json.loads(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
    except Exception:  # noqa: BLE001 -- see docstring
        logger.warning("intake LLM fallback failed; using the parser's result", exc_info=True)
        return fields

    for key in ("name", "age", "gender", "village", "phone", "pregnancy_stage"):
        if getattr(fields, key) is None and data.get(key) not in (None, ""):
            try:
                setattr(fields, key, data[key])
            except Exception:  # noqa: BLE001 -- a bad type for one field
                continue                          # must not lose the others
    return fields
