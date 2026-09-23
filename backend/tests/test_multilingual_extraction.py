"""The rule-based extractor has to work in the languages the app offers.

The app ships a UI in six languages, and Agent 1 falls back to this
regex extractor whenever the LLM call fails or returns something
unusable -- which is exactly the moment the fallback matters. Until these
patterns existed it covered English, romanised Hindi and Devanagari only,
so a Tamil, Telugu or Bengali visit worked while the model was healthy
and produced an empty record the moment it was not.

CAVEAT, and it belongs in the file rather than in a commit message:
these patterns are transliteration-checked, NOT validated by native
speakers, and they have never been run against real Bhashini output in
these languages. They are a floor, not a measurement. What they
guarantee is that a failed LLM call degrades to *something* rather than
to silence; how much they catch in the field is unknown, and closing
that needs the same recording exercise `docs/EVIDENCE.md` section 2 asks
for.
"""
import pytest

from app.agents.agent1_voice_comprehension import extract

# One visit, four scripts: 7 months pregnant, fever 101, iron tablets not
# taken, severe headache (an NHM immediate-referral danger sign).
CASES = {
    "bengali": "বয়স 28 বছর, 7 মাস গর্ভ। জ্বর 101। ওষুধ খায়নি। মাথা ব্যথা।",
    "tamil": "வயது 28, 7 மாதம் கர்ப்பம். காய்ச்சல் 101. மாத்திரை எடுக்கவில்லை. தலைவலி.",
    "telugu": "వయసు 28, 7 నెలల గర్భం. జ్వరం 101. మాత్ర తీసుకోలేదు. తలనొప్పి.",
    "hinglish": "28 saal, 7 mahine ki pregnancy. Fever 101. Iron tablets nahi li. Tez sir dard.",
}


@pytest.mark.parametrize("language", sorted(CASES))
def test_the_same_visit_extracts_in_every_offered_script(language):
    fields = extract(CASES[language])

    assert fields.pregnancy_stage == "7 months", f"{language}: gestational age lost"
    assert fields.temperature_c == 101.0, f"{language}: fever lost"
    assert fields.medication_compliance == "non_compliant", (
        f"{language}: a missed iron course read as compliant or unknown"
    )
    assert fields.danger_signs, (
        f"{language}: severe headache is an NHM immediate-referral danger sign "
        "and was not picked up"
    )


@pytest.mark.parametrize("language", sorted(CASES))
def test_a_visit_in_any_script_is_not_silently_unassessed(language):
    """The failure this guards against is not a wrong answer, it is a
    confident empty one: an extractor that reads nothing hands the
    classifier a blank record, and a blank record used to come back as a
    reassuring LOW rather than as UNASSESSED."""
    from app.agents.agent2_risk_classification import classify

    result = classify(extract(CASES[language]))
    assert result.risk_level == "HIGH", (
        f"{language}: a danger sign plus fever did not reach HIGH -- got "
        f"{result.risk_level}"
    )
    assert result.drivers, f"{language}: a flag with no explainable driver"


def test_social_risk_factors_are_read_in_each_script():
    assert "absent spouse" in extract("স্বামী বাইরে আছে।").social_risk_factors
    assert "household isolation" in extract("அவர் தனியாக இருக்கிறார்.").social_risk_factors
    assert "household isolation" in extract("ఆమె ఒంటరిగా ఉంది.").social_risk_factors
    assert "economic stress" in extract("টাকা নেই।").social_risk_factors
