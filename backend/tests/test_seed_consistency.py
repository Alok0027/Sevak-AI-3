"""Seeded history has to be something the system produced, not asserted.

It used to be `random.choices(RISK_LEVELS, weights=[0.15, 0.30, 0.55])`
with `structured_json="{}"` and an unrelated `random.uniform` score. A
demo patient could be HIGH with no readings behind her, drivers that
referred to nothing she had, and a score contradicting her own label --
all of it visible to anyone who clicked a row.
"""
import json

import pytest

from app.agents.agent2_risk_classification import classify
from app.schemas.visit import ExtractedFields
from scripts import seed_synthetic_data as seeder


def test_generated_vitals_are_classifiable():
    """Vitals the classifier cannot read would seed a history of
    UNASSESSED visits, which is the opposite of the point."""
    for _ in range(200):
        result = classify(ExtractedFields(**seeder.make_visit_vitals()))
        assert result.risk_level in ("HIGH", "MEDIUM", "LOW")


def test_generated_vitals_are_physiologically_plausible():
    """A clinician glancing at the demo should not find a woman at 250/30."""
    for _ in range(200):
        v = seeder.make_visit_vitals()
        assert 80 <= v["bp_systolic"] <= 200
        assert 50 <= v["bp_diastolic"] <= 130
        assert v["bp_systolic"] > v["bp_diastolic"]
        assert 60 <= v["blood_sugar_random"] <= 400
        assert 34.0 <= v["temperature_c"] <= 41.0


def test_the_generator_produces_more_than_one_risk_level():
    """A demo where every patient is LOW shows nothing; one where every
    patient is HIGH is not believable."""
    levels = {classify(ExtractedFields(**seeder.make_visit_vitals())).risk_level
              for _ in range(300)}
    assert len(levels) >= 2, f"only ever produced {levels}"


def test_uci_units_are_converted(tmp_path, monkeypatch):
    """The dataset records blood sugar in mmol/L and temperature in
    Fahrenheit; this project uses mg/dL and Celsius. Loaded raw, every
    glucose reading sits around 7 -- far under the 126 mg/dL threshold --
    and every temperature near 98, which reads as a fatal fever. Both
    failures are silent: the seeder runs, and the data is quietly wrong.
    """
    csv = tmp_path / "maternal_vitals.csv"
    csv.write_text(
        "Age,SystolicBP,DiastolicBP,BS,BodyTemp,HeartRate,RiskLevel\n"
        "25,140,90,15.0,98.0,86,high risk\n"
    )
    monkeypatch.setattr(seeder, "VITALS_CSV", csv)
    monkeypatch.setattr(seeder, "_VITALS_ROWS", None)

    row = seeder.make_visit_vitals()
    assert row["bp_systolic"] == 140 and row["bp_diastolic"] == 90
    # 15.0 mmol/L is ~270 mg/dL -- well over the NHM diabetes threshold.
    assert 265 <= row["blood_sugar_random"] <= 275, row["blood_sugar_random"]
    # 98.0 F is 36.7 C -- normal, not a fever.
    assert 36.5 <= row["temperature_c"] <= 36.8, row["temperature_c"]


def test_a_malformed_csv_row_does_not_cost_the_whole_file(tmp_path, monkeypatch):
    csv = tmp_path / "maternal_vitals.csv"
    csv.write_text(
        "Age,SystolicBP,DiastolicBP,BS,BodyTemp,HeartRate,RiskLevel\n"
        "25,,,,,,high risk\n"
        "30,120,80,7.0,98.0,76,low risk\n"
    )
    monkeypatch.setattr(seeder, "VITALS_CSV", csv)
    monkeypatch.setattr(seeder, "_VITALS_ROWS", None)
    assert len(seeder._load_vitals_rows()) == 1


def test_no_csv_falls_back_to_the_generator(tmp_path, monkeypatch):
    """The dataset is optional. Nothing in the demo may depend on a file
    somebody has to download first."""
    monkeypatch.setattr(seeder, "VITALS_CSV", tmp_path / "absent.csv")
    monkeypatch.setattr(seeder, "_VITALS_ROWS", None)
    assert seeder.make_visit_vitals()["bp_systolic"] > 0
