"""Parsing real Bhashini output, which differs from the mock transcripts in
three ways that each broke extraction silently:

  * Devanagari script rather than romanized Hinglish.
  * No punctuation at all -- no commas, full stops or dandas.
  * Numbers written as words ("बत्तीस साल"), including phone numbers
    dictated one digit at a time ("एक दो तीन चार...").

The transcript in test_real_bhashini_transcript_fills_every_field is a
verbatim capture from a physical device, kept as-is (including the ASR's
duplicated opening name) so this stays a test of real output rather than
of tidied-up sample text.
"""
from app.agents.agent1_voice_comprehension import extract as clinical_extract
from app.agents.agent2_risk_classification import classify
from app.services.hindi_numbers import parse_spoken_number, spoken_digits_to_phone
from app.services.patient_intake import extract
from app.services.vitals_parsing import find_blood_sugar, find_bp

REAL_TRANSCRIPT = (
    "सुंदर देवी सुनीता देवी उम्र बत्तीस साल महिला गांव वघोली छ महीना "
    "प्रेग्नेंट फ़ोन नंबर एक दो तीन चार पाँच छः एक दो तीन चार "
    "पति ने घर से लात मार के बाहर निकाल दिया आँख फूट गई हाथ टूट गया "
    "सर भी फट गया है"
)


def test_real_bhashini_transcript_fills_every_field():
    fields = extract(REAL_TRANSCRIPT)
    assert fields.age == 32  # "बत्तीस", not "32"
    assert fields.gender == "female"
    assert fields.village == "वघोली"  # no comma after it to stop on
    assert fields.phone == "1234561234"  # ten separately spoken digits
    assert fields.pregnancy_stage == "6 months"
    assert fields.name is not None and "सुनीता" in fields.name


def test_a_remark_with_no_patient_details_yields_nothing():
    """The opening words of a sentence are only a name once something else
    confirms this is a patient description -- otherwise any passing remark
    registers somebody."""
    fields = extract("this is just background noise with no real details")
    assert fields.name is None
    assert fields.age is None


def test_spoken_numbers():
    assert parse_spoken_number("बत्तीस") == 32
    assert parse_spoken_number("एक सौ चालीस") == 140  # compound
    assert parse_spoken_number("३२") == 32  # Devanagari digits
    assert parse_spoken_number("32") == 32
    assert spoken_digits_to_phone("एक दो तीन चार पाँच छः एक दो तीन चार") == "1234561234"
    # A stray number word is not the start of a phone number.
    assert spoken_digits_to_phone("उम्र दो तीन साल") is None


def test_bp_spoken_as_words():
    assert find_bp("बीपी एक सौ पचास बटा पंचानवे") == (150, 95)
    assert find_bp("बीपी 140 बटा 90") == (140, 90)
    assert find_bp("BP 140 over 90") == (140, 90)


def test_an_unreadable_bp_is_dropped_rather_than_guessed():
    """A wrong BP is worse than a missing one: it reaches the NHM
    thresholds and gets classified. With the separator optional the regex
    would pair two halves of the systolic reading ("एक सौ" + "पचास") into
    a plausible-looking 100/50."""
    assert find_bp("बीपी एक सौ पचास बटा अपठनीयशब्द") is None
    assert find_bp("बीपी एक बटा दो") is None  # implausible range


def test_fasting_and_random_sugar_are_told_apart():
    assert find_blood_sugar("खाली पेट शुगर एक सौ चालीस") == (140, None)
    assert find_blood_sugar("शुगर दो सौ पचास") == (None, 250)


def test_a_reading_of_150_is_high_fasting_but_only_medium_random():
    """The reason the two are stored separately at all."""
    fasting = clinical_extract("खाली पेट शुगर 150")
    assert classify(fasting).risk_level == "HIGH"

    random_reading = clinical_extract("शुगर 150")
    assert classify(random_reading).risk_level == "MEDIUM"


def test_reported_violence_escalates_to_high_on_its_own():
    """Before this rule the engine knew only BP, temperature, medication
    and three social factors, so a visit reporting an assault with broken
    bones scored LOW."""
    fields = clinical_extract(REAL_TRANSCRIPT)
    assert fields.violence_or_injury == ["physical violence", "injury reported"]

    result = classify(fields)
    assert result.risk_level == "HIGH"
    assert any("violence" in d.reason.lower() for d in result.drivers)


def test_clinical_extractor_reads_spoken_numbers_too():
    fields = clinical_extract("रानी बीस साल छ महीना बीपी एक सौ साठ बटा एक सौ")
    assert fields.age == 20
    assert fields.pregnancy_stage == "6 months"
    assert (fields.bp_systolic, fields.bp_diastolic) == (160, 100)
