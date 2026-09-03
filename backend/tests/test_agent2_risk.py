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
