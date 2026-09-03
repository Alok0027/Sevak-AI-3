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
