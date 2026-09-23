from app.agents.agent2_risk_classification import classify
from app.schemas.visit import ExtractedFields


def test_high_bp_plus_noncompliance_is_high_risk():
    fields = ExtractedFields(bp_systolic=140, bp_diastolic=90, medication_compliance="non_compliant")
    result = classify(fields)
    assert result.risk_level == "HIGH"
    assert len(result.drivers) >= 2


def test_normal_vitals_is_low_risk():
    fields = ExtractedFields(bp_systolic=110, bp_diastolic=70, medication_compliance="compliant")
    result = classify(fields)
    assert result.risk_level == "LOW"


def test_elevated_bp_alone_is_medium_risk():
    fields = ExtractedFields(bp_systolic=132, bp_diastolic=86, medication_compliance="compliant")
    result = classify(fields)
    assert result.risk_level == "MEDIUM"


def test_every_flag_has_at_least_one_driver():
    """FR-03.2: every risk flag must include an explainable driver."""
    fields = ExtractedFields()
    result = classify(fields)
    assert len(result.drivers) >= 1


def test_antenatal_wording_only_appears_for_a_pregnant_patient():
    """FR-03.2 is about the explanation, not just the label.

    The thresholds below are correct for any adult, but every reason string
    was written as though the patient were always pregnant. Once seeded
    referral letters became visible, a 49-year-old man's letter read "meets
    NHM pre-eclampsia risk threshold for pregnant patients" -- a wrong
    explanation attached to a right referral, printed on a document that
    goes to a PHC.
    """
    vitals = dict(
        bp_systolic=167,
        bp_diastolic=105,
        temperature_c=38.4,
        medication_compliance="non_compliant",
    )

    pregnant = classify(ExtractedFields(pregnancy_stage="7 months", **vitals))
    not_pregnant = classify(ExtractedFields(**vitals))

    # The clinical call is unchanged -- only the wording is conditional.
    assert pregnant.risk_level == not_pregnant.risk_level == "HIGH"
    assert pregnant.risk_score == not_pregnant.risk_score

    pregnant_text = " ".join(d.reason for d in pregnant.drivers).lower()
    other_text = " ".join(d.reason for d in not_pregnant.drivers).lower()

    assert "pre-eclampsia" in pregnant_text
    assert "during pregnancy" in pregnant_text
    assert "anc protocol" in pregnant_text

    for antenatal_only in ("pre-eclampsia", "pregnan", "anc protocol", "gestational"):
        assert antenatal_only not in other_text, (
            f"{antenatal_only!r} reached a patient with no pregnancy recorded"
        )
    # And it still says why she was referred, rather than going quiet.
    assert "140/90" in other_text
