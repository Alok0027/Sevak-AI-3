"""Two failures found by speaking into the app rather than reading the code.

The transcript was Bhashini's, verbatim, and correct:

    "जानकी कुमारी तबीयत खराब है बत्तीस वर्ष महिला है बी पी है
     एक सौ साठ बटा एक सौ तीस बुखार बहुत तेज है ..."

Speech recognition did its job. Extraction returned no blood pressure at
all and a four-word name. Both are the kind of thing that only shows up
when somebody actually speaks a sentence a person would say.
"""
import pytest

from app.services.patient_intake import extract
from app.services.vitals_parsing import find_bp

REAL_TRANSCRIPT = (
    "जानकी कुमारी तबीयत खराब है बत्तीस वर्ष महिला है बी पी है एक सौ साठ बटा "
    "एक सौ तीस बुखार बहुत तेज है एक सौ आठ डिग्री आयरन की गोली नहीं ले रही है"
)


# ---------------------------------------------------------------------------
# A filler word between the label and the reading
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("said, expected", [
    # Nobody says "BP 160 by 130". They say "BP *is* 160 by 130".
    ("बी पी है एक सौ साठ बटा एक सौ तीस", (160, 130)),
    ("बी पी का एक सौ साठ बटा एक सौ तीस", (160, 130)),
    ("बीपी है 150 बटा 100", (150, 100)),
    ("BP is 132 by 86", (132, 86)),
    ("BP was 140 over 90", (140, 90)),
    # Still works with no filler at all.
    ("बीपी एक सौ चालीस बटा नब्बे", (140, 90)),
])
def test_a_word_between_the_label_and_the_number(said, expected):
    assert find_bp(said) == expected


def test_the_filler_gap_cannot_reach_into_the_next_clause():
    """The gap has to stay closed. A permissive one lets "BP" bind to a
    number from a different measurement -- and the result goes straight to
    the NHM thresholds, where 220/0 is not obviously wrong."""
    assert find_bp("बीपी नॉर्मल है, शुगर दो सौ बीस") is None
    assert find_bp("बीपी ठीक है और वजन पचपन किलो है") is None


def test_the_real_transcript_yields_its_blood_pressure():
    fields = extract(REAL_TRANSCRIPT)
    assert (fields.bp_systolic, fields.bp_diastolic) == (160, 130)


# ---------------------------------------------------------------------------
# A name that runs into the complaint
# ---------------------------------------------------------------------------

def test_the_name_stops_before_the_complaint():
    """An ASHA says the name and goes straight into what is wrong. Without
    a boundary, "तबीयत खराब" ("unwell") became part of the name."""
    assert extract(REAL_TRANSCRIPT).name == "जानकी कुमारी"


@pytest.mark.parametrize("said, complaint", [
    ("सुनीता देवी तबीयत खराब है बत्तीस साल", "तबीयत"),
    ("कमला बीमार है तीस साल", "बीमार"),
    ("रेखा देवी बुखार है पच्चीस साल", "बुखार"),
    ("मीरा पाटील चक्कर आ रहे हैं अट्ठाईस साल", "चक्कर"),
])
def test_complaints_never_end_up_inside_a_name(said, complaint):
    """The invariant, stated as what must not happen rather than what must.

    With no age and no "नाम" anchor the extractor declines to guess a name
    at all -- it returns None and the ASHA types it, or the LLM fallback
    fills it when there is signal. That is a deliberate choice: a blank
    field is honest, an invented one is not. What must never happen either
    way is a name with a symptom welded onto it.
    """
    name = extract(said).name
    assert name is None or complaint not in name


def test_no_age_and_no_anchor_means_no_guess():
    """Documents the conservative behaviour above, so a future change that
    starts guessing is a visible decision rather than a side effect."""
    assert extract("कमला बीमार है").name is None


def test_ordinary_names_are_untouched():
    """The boundary list must not eat real names."""
    assert extract("सुनीता देवी बत्तीस साल गांव वघोली").name == "सुनीता देवी"
    assert extract("नाम मीरा पाटील है").name == "मीरा पाटील"
    assert extract("Sunita Devi, 32 saal, gaon Wagholi").name == "Sunita Devi"


def test_the_rest_of_the_real_transcript_still_parses():
    fields = extract(REAL_TRANSCRIPT)
    assert fields.age == 32
    assert fields.gender == "female"
