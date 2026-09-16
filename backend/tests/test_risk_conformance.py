"""Does the risk engine classify the way the NHM guidance says it should?

Read the name carefully: this measures **conformance**, not clinical
accuracy, and the distinction is the whole point of the file.

Every case below carries the sentence from the NHM corpus that decides
its expected label. That makes the labels traceable to a published
source rather than to somebody's opinion. What it does *not* make them is
independent of the system under test: `classify()` encodes thresholds
drawn from the same guidance. So a high score here proves the code
implements the protocol it claims to implement, and proves nothing about
whether that protocol correctly identifies a woman in danger.

Stated plainly for anyone quoting a number out of this file:

    This is a conformance result. It is NOT a clinical validation.
    Clinical validation needs labels from a clinician against real
    visits, which this project has not done.

What it does catch, and what makes it worth running:

  * Boundary errors. 139/89 and 140/90 are one mmHg apart and on
    opposite sides of the pre-eclampsia threshold. An off-by-one in a
    comparison is invisible in a demo and lethal in the field.
  * Escalation on combination. Several mild findings on one woman should
    not each be shrugged off in isolation.
  * The silence case. A visit that recovered no clinical signal must come
    back UNASSESSED, never LOW. Reporting "low risk" for a woman nobody
    actually assessed is the most dangerous output this system can
    produce, because it looks like a result.

Run the report:

    python -m pytest tests/test_risk_conformance.py -s -q
"""
from __future__ import annotations

from collections import Counter

import pytest

from app.schemas.visit import ExtractedFields
from app.agents.agent2_risk_classification import classify

# Case = (id, expected, fields, the NHM sentence that decides it, known_gap)
#
# known_gap is None when the engine agrees today. Where it is a string,
# the engine is known to disagree and the string says why the expected
# label is the right one. Those cases are marked xfail(strict=True), so
# the suite stays green while the gap is recorded rather than hidden --
# and turns red the moment somebody fixes the engine, which is the prompt
# to come back here and clear the marker.
CASES: list[tuple[str, str, dict, str, str | None]] = [
    # ---- Blood pressure, around the pre-eclampsia threshold ----------
    ("bp_160_110_severe", "HIGH", {"bp_systolic": 160, "bp_diastolic": 110},
     "antenatal_care.md: 'If the BP is high (more than 140/90 mmHg; or diastolic more than 90'", None),
    ("bp_140_90_exact", "HIGH", {"bp_systolic": 140, "bp_diastolic": 90},
     "antenatal_care.md: at the 140/90 threshold itself", None),
    ("bp_139_89_just_under", "MEDIUM", {"bp_systolic": 139, "bp_diastolic": 89},
     "Below 140/90, at or above the elevated band (130/85): closer monitoring", None),
    ("bp_142_80_systolic_only", "HIGH", {"bp_systolic": 142, "bp_diastolic": 80},
     "Either limb at or above threshold is sufficient; 142 systolic qualifies", None),
    ("bp_120_78_normal", "LOW", {"bp_systolic": 120, "bp_diastolic": 78},
     "Normal range, below the 130/85 elevated band", None),
    ("bp_130_85_elevated_edge", "MEDIUM", {"bp_systolic": 130, "bp_diastolic": 85},
     "At the elevated band, below 140/90", None),

    # ---- Blood sugar -------------------------------------------------
    ("sugar_fasting_130", "HIGH", {"blood_sugar_fasting": 130},
     "gestational_diabetes.md: fasting at or above 126 mg/dL meets the diabetes threshold", None),
    ("sugar_fasting_125_edge", "MEDIUM", {"blood_sugar_fasting": 125},
     "Fasting 100-125 is the elevated band, below the 126 diabetes threshold", None),
    ("sugar_fasting_92_normal", "LOW", {"blood_sugar_fasting": 92},
     "Below the 100 mg/dL elevated band", None),
    ("sugar_random_210", "HIGH", {"blood_sugar_random": 210},
     "gestational_diabetes.md: 'post-prandial above 200 mg/dL at any point'", None),

    # ---- Fever -------------------------------------------------------
    # MEDIUM, not HIGH. Fever is not in antenatal_care.md's immediate
    # referral list; the guidance is "prompt evaluation", which is the
    # MEDIUM band. An earlier draft of this file labelled it HIGH on
    # instinct, which is the exact mistake this file exists to avoid --
    # a label has to come from the text, not from how serious it sounds.
    ("temp_38_5_fever", "MEDIUM", {"temperature_c": 38.5},
     "Fever at or above 38.0C: prompt evaluation. Not on the immediate-referral list.", None),
    ("temp_37_0_normal", "LOW", {"temperature_c": 37.0},
     "Below the 38.0C fever threshold", None),

    # ---- Violence: HIGH on its own, whatever else is normal ----------
    ("violence_with_normal_vitals", "HIGH",
     {"bp_systolic": 118, "bp_diastolic": 76, "violence_or_injury": ["bruising on arms"]},
     "Any reported violence or injury is HIGH on its own, whatever the other readings", None),

    # ---- Medication compliance --------------------------------------
    ("iron_non_compliant", "MEDIUM",
     {"medication_compliance": "non_compliant", "medication_compliance_detail": "IFA tablets"},
     "antenatal_care.md: a missed IFA course raises anaemia and complication risk", None),
    ("iron_compliant", "LOW",
     {"medication_compliance": "compliant", "medication_compliance_detail": "IFA tablets"},
     "Taking medication as prescribed; nothing abnormal", None),

    # ---- Combination: several mild findings on one woman -------------
    # Both stay MEDIUM. Nothing in the corpus says two elevated findings
    # compound into an immediate referral, and inventing that rule here
    # would be this file asserting clinical judgement it does not have.
    # Worth asking a clinician; not worth assuming.
    ("elevated_bp_plus_non_compliance", "MEDIUM",
     {"bp_systolic": 134, "bp_diastolic": 86, "medication_compliance": "non_compliant",
      "medication_compliance_detail": "IFA tablets"},
     "Two sub-threshold findings; no corpus rule compounds them to HIGH", None),
    ("elevated_sugar_plus_elevated_bp", "MEDIUM",
     {"bp_systolic": 132, "bp_diastolic": 85, "blood_sugar_fasting": 118},
     "Two sub-threshold findings; no corpus rule compounds them to HIGH", None),

    # ---- Silence vs assessment --------------------------------------
    ("nothing_recovered", "UNASSESSED", {},
     "No clinical signal recovered; nothing to assess. Must not read as LOW.", None),

    # ---- Danger signs -----------------------------------------------
    # These two were the gap this file was written to find. Before the
    # fix, ExtractedFields had no field for a reported symptom at all:
    # Agent 1 dropped the words and the classifier scored the vitals it
    # had. The first case came back LOW.
    ("danger_sign_with_normal_bp", "HIGH",
     {"bp_systolic": 118, "bp_diastolic": 76,
      "danger_signs": ["Severe headache, with or without blurred vision"]},
     "antenatal_care.md danger signs: 'Severe headache with blurred vision' is on the "
     "immediate-referral list, and the corpus states these signs 'are urgent whatever "
     "the blood pressure reading happens to be'.",
     None),  # was: returned LOW over "no abnormal findings recorded". Fixed.
    ("danger_sign_no_vitals", "HIGH",
     {"danger_signs": ["Severe headache, with or without blurred vision"]},
     "Same danger-sign list; urgent regardless of whether a BP was taken.",
     None),  # was: returned UNASSESSED, discarding the danger sign. Fixed.
]


def _classify(fields: dict) -> str:
    return classify(ExtractedFields(**fields)).risk_level


@pytest.mark.parametrize(
    "case_id,expected,fields,source,known_gap",
    [
        pytest.param(*c, marks=pytest.mark.xfail(reason=c[4], strict=True))
        if c[4] else pytest.param(*c)
        for c in CASES
    ],
    ids=[c[0] for c in CASES],
)
def test_case_matches_nhm_guidance(case_id, expected, fields, source, known_gap):
    actual = _classify(fields)
    assert actual == expected, (
        f"\n  case      : {case_id}"
        f"\n  expected  : {expected}"
        f"\n  got       : {actual}"
        f"\n  basis     : {source}"
    )


def test_report_conformance_matrix(capsys):
    """Prints the confusion matrix and the headline figure.

    Not an assertion on the score. A threshold here would either be so
    low it passes anything or so high it fails the build the first time
    somebody adds a hard case -- and either way the number is what
    matters, not a green tick.
    """
    labels = ["HIGH", "MEDIUM", "LOW", "UNASSESSED"]
    matrix: Counter[tuple[str, str]] = Counter()
    wrong: list[tuple[str, str, str, str]] = []

    for case_id, expected, fields, source, known_gap in CASES:
        actual = _classify(fields)
        matrix[(expected, actual)] += 1
        if actual != expected:
            wrong.append((case_id, expected, actual, known_gap or source))

    correct = sum(n for (e, a), n in matrix.items() if e == a)
    total = len(CASES)

    with capsys.disabled():
        print("\n\n  SevakAI risk engine — NHM threshold conformance")
        print("  " + "=" * 62)
        print(f"  {correct} of {total} cases classified as the NHM guidance specifies "
              f"({correct / total * 100:.1f}%)")
        print()
        print("  Confusion matrix (rows = expected, columns = predicted)")
        print("  " + " " * 13 + "".join(f"{c:>12}" for c in labels))
        for exp in labels:
            row = "".join(f"{matrix[(exp, act)] or '.':>12}" for act in labels)
            print(f"  {exp:<13}{row}")
        print()

        for label in labels:
            tp = matrix[(label, label)]
            fp = sum(matrix[(e, label)] for e in labels if e != label)
            fn = sum(matrix[(label, a)] for a in labels if a != label)
            if tp + fn == 0:
                continue
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn)
            print(f"  {label:<12} precision {precision:>5.2f}   recall {recall:>5.2f}   "
                  f"(n={tp + fn})")

        if wrong:
            print("\n  DISAGREEMENTS — each is a gap in the engine, not in the labels:")
            for case_id, expected, actual, source in wrong:
                print(f"    {case_id}: expected {expected}, got {actual}")
                print(f"      basis: {source}")

        print()
        print("  THIS IS A CONFORMANCE RESULT, NOT A CLINICAL VALIDATION.")
        print("  Labels come from the NHM corpus in backend/nhm_corpus, which is")
        print("  also where classify()'s thresholds come from. It demonstrates the")
        print("  code implements the protocol it cites. It does not demonstrate")
        print("  that the protocol catches every woman at risk -- that needs a")
        print("  clinician labelling real visits.")
        print()
