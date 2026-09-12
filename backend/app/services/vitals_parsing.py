"""Blood pressure and blood sugar parsing, shared by the registration
extractor (patient_intake) and the clinical one (agent1).

Both need to read the same readings off the same kind of speech -- a
baseline at registration, and a per-visit measurement during a home visit
-- so the patterns live here once rather than drifting apart in two files.

Everything accepts romanized Hinglish and Devanagari, and numbers spoken
as words, because Bhashini returns Devanagari with numbers written out
("बीपी एक सौ चालीस") while the mock/demo transcripts are romanized.
"""
import re

from app.services.hindi_numbers import SPOKEN_NUMBER_PATTERN, parse_spoken_number

_NUM = SPOKEN_NUMBER_PATTERN

# A misread reading is worse than none: it feeds the NHM thresholds
# directly, so an out-of-range parse (a stray "एक" read as a systolic of
# 1) must be discarded rather than classified. These are deliberately wide
# -- wide enough to admit any real measurement, narrow enough to reject
# parse artefacts.
_PLAUSIBLE_SYSTOLIC = range(60, 261)
_PLAUSIBLE_DIASTOLIC = range(30, 181)
_PLAUSIBLE_SUGAR = range(30, 801)

# The systolic/diastolic separator is spoken many ways ("140 over 90",
# "140/90", "140 बटा 90") and sometimes not at all ("बीपी 140 90").
_BP_LEAD = r"(?:BP|बीपी|बी\.?\s?पी\.?|blood\s*pressure|रक्तचाप)"
_BP_SEPARATOR = r"over|by|/|-|बटा|बाय|पर"
# Tried in this order deliberately. With the separator optional, an
# unrecognised second number lets the regex backtrack and pair up two
# fragments of the *first* one instead -- "एक सौ पचास बटा पंचानवे" comes
# back as 100/50, a wrong reading that is plausible enough to pass every
# range check and reach the risk engine. Requiring the separator first
# means that case finds no match at all, which is the safe answer.
_BP_WITH_SEPARATOR_RE = re.compile(
    rf"{_BP_LEAD}\s*({_NUM})\s*(?:{_BP_SEPARATOR})\s*({_NUM})", re.IGNORECASE
)
_BP_BARE_RE = re.compile(rf"{_BP_LEAD}\s*({_NUM})\s+({_NUM})", re.IGNORECASE)
# If a separator was actually spoken, the bare form must not be tried at
# all: it would pair two halves of the systolic reading across it.
_BP_HAS_SEPARATOR_RE = re.compile(rf"{_BP_LEAD}.{{0,40}}?(?:{_BP_SEPARATOR})", re.IGNORECASE)

# "खाली पेट" (empty stomach) is how fasting is actually said in the field;
# "फास्टिंग" is the borrowed term. Anything else measured is treated as a
# random reading, which is what the NHM cutoffs assume.
_FASTING_WORDS = r"खाली\s*पेट|फास्टिंग|fasting|empty\s*stomach"
_SUGAR_WORDS = r"शुगर|शक्कर|ब्लड\s*शुगर|sugar|glucose|मधुमेह"

_SUGAR_FASTING_RE = re.compile(
    rf"(?:{_FASTING_WORDS})(?:\s+(?:{_SUGAR_WORDS}))?\D{{0,15}}?({_NUM})", re.IGNORECASE
)
_SUGAR_FASTING_AFTER_RE = re.compile(
    rf"(?:{_SUGAR_WORDS})\D{{0,15}}?({_NUM})\s*(?:mg|एमजी)?\D{{0,10}}?(?:{_FASTING_WORDS})", re.IGNORECASE
)
_SUGAR_ANY_RE = re.compile(rf"(?:{_SUGAR_WORDS})\D{{0,15}}?({_NUM})", re.IGNORECASE)


def find_bp(transcript: str) -> tuple[int, int] | None:
    """(systolic, diastolic) if a blood-pressure reading was stated."""
    patterns = [_BP_WITH_SEPARATOR_RE]
    if not _BP_HAS_SEPARATOR_RE.search(transcript):
        patterns.append(_BP_BARE_RE)
    for pattern in patterns:
        m = pattern.search(transcript)
        if not m:
            continue
        systolic = parse_spoken_number(m.group(1))
        diastolic = parse_spoken_number(m.group(2))
        if systolic in _PLAUSIBLE_SYSTOLIC and diastolic in _PLAUSIBLE_DIASTOLIC:
            return systolic, diastolic
    return None


def find_blood_sugar(transcript: str) -> tuple[int | None, int | None]:
    """(fasting, random) blood sugar in mg/dL, either or both None.

    Kept as two values rather than one because the NHM thresholds differ
    sharply -- 150 is abnormal fasting but unremarkable random -- so a
    single undifferentiated number cannot be scored safely.
    """
    for pattern in (_SUGAR_FASTING_RE, _SUGAR_FASTING_AFTER_RE):
        if m := pattern.search(transcript):
            value = parse_spoken_number(m.group(1))
            if value in _PLAUSIBLE_SUGAR:
                return value, None

    if m := _SUGAR_ANY_RE.search(transcript):
        value = parse_spoken_number(m.group(1))
        if value in _PLAUSIBLE_SUGAR:
            return None, value
    return None, None
