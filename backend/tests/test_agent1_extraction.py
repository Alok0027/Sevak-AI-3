from app.agents.agent1_voice_comprehension import extract


def test_extracts_demo_script_transcript():
    """SRS section 9.1, 1:00-1:30 -- must extract every field the demo narrates."""
    transcript = (
        "Meera Patil, 28 saal, 7 mahine ki pregnancy. Aaj BP 140 over 90 tha. "
        "Usne pichle 2 hafte se iron tablets nahi li. Pati bahar gaya hua hai."
    )
    fields = extract(transcript)

    assert fields.patient_name == "Meera Patil"
    assert fields.age == 28
    assert fields.pregnancy_stage == "7 months"
    assert fields.bp_systolic == 140
    assert fields.bp_diastolic == 90
    assert fields.medication_compliance == "non_compliant"
    assert "absent spouse" in fields.social_risk_factors


def test_compliant_normal_reading():
    transcript = "Meera Patil, 28 saal. Usne saari tablets time par li."
    fields = extract(transcript)
    assert fields.medication_compliance == "compliant"


def test_no_medication_mentioned_is_unknown():
    transcript = "Ramesh Kumar, 45 saal. BP normal tha."
    fields = extract(transcript)
    assert fields.medication_compliance == "unknown"


# --- Devanagari ---------------------------------------------------------
# Bhashini's real Hindi ASR returns Devanagari, not the romanized Hinglish
# the mock STT produces. Every test above this line runs on romanized text,
# so none of them would have caught the extractor silently matching nothing
# on real speech -- which reads downstream as a patient with no vitals
# rather than one who was never assessed.


def test_devanagari_visit_extracts_the_same_clinical_record():
    transcript = (
        "मीरा पाटिल, 28 साल, सात महीने की गर्भवती। बीपी 140 बटा 90। "
        "बुखार 101। वजन 52 किलो। आयरन की गोली नहीं ली पिछले 2 हफ्ते। "
        "पति बाहर गया हुआ है।"
    )
    fields = extract(transcript)

    assert fields.age == 28
    assert fields.pregnancy_stage == "7 months"  # spoken as the word "सात"
    assert fields.bp_systolic == 140
    assert fields.bp_diastolic == 90
    assert fields.temperature_c == 101.0
    assert fields.weight_kg == 52.0
    assert fields.medication_compliance == "non_compliant"
    assert "absent spouse" in fields.social_risk_factors


def test_devanagari_bp_accepts_a_slash_and_a_bare_degree_reading():
    fields = extract("बीपी 150/95, 101 डिग्री, 48 किलो, नौ महीने")
    assert (fields.bp_systolic, fields.bp_diastolic) == (150, 95)
    assert fields.temperature_c == 101.0
    assert fields.weight_kg == 48.0
    assert fields.pregnancy_stage == "9 months"


def test_devanagari_with_nothing_clinical_stays_empty():
    """An empty record must not be mistaken for a healthy one -- no value
    should be invented when the ASHA didn't state one."""
    fields = extract("मरीज ठीक है")
    assert fields.bp_systolic is None
    assert fields.temperature_c is None
    assert fields.medication_compliance == "unknown"
