"""
NHM threshold engine for Agent 2 risk classification (FR-03.1, FR-03.2).

The deterministic half of risk classification. Retrieval over the NHM
corpus lives next door in `nhm_retrieval.py`, and Agent 2 combines them:
retrieved guidance supplies the reasoning and the citation, these rules
supply the floor underneath it.

This module was once described as a stand-in "until the real RAG pipeline
is built". It is not a stand-in any more, and it is not superseded either.
It is the part of the system that cannot fail quietly. Retrieval can miss,
a corpus can be absent, a model can have an off day -- and every one of
those failures produces a *less* alarming answer. So the rules below run on
every visit regardless, and the final risk level is the higher of what they
say and what the retrieved reasoning says. A woman at 160/110 is HIGH even
if the search returns nothing at all.

The thresholds encoded here are the published NHM figures, and the corpus
documents they came from are in ../nhm_corpus:

    BP >=140/90            antenatal_care.md (and diastolic >110 as
                           imminent eclampsia)
    fasting glucose >=126  gestational_diabetes.md
    random glucose >=200   gestational_diabetes.md
    temperature >=38.0C    antenatal_care.md, PHC within 24 hours

Changing a number here without changing the corpus -- or the reverse --
leaves the system citing one threshold and applying another, which is
harder to notice than either being wrong on its own.
"""
from dataclasses import dataclass

from app.schemas.visit import ExtractedFields, RiskDriver

HIGH_BP_SYSTOLIC = 140
HIGH_BP_DIASTOLIC = 90
ELEVATED_BP_SYSTOLIC = 130
ELEVATED_BP_DIASTOLIC = 85
LOW_TEMP_FEVER_C = 38.0
# Diabetes thresholds, mg/dL. Fasting and random are judged separately --
# 150 is diabetic-range fasting but unremarkable as a random reading, so
# scoring one against the other's cutoff would be actively misleading.
HIGH_FASTING_SUGAR = 126
ELEVATED_FASTING_SUGAR = 100
HIGH_RANDOM_SUGAR = 200
ELEVATED_RANDOM_SUGAR = 140


# Danger signs arrive already identified, in extracted.danger_signs --
# Agent 1 matches them against the transcript (see _DANGER_SIGN_RULES
# there), because this module only ever sees extracted fields and the
# words are in the speech.
#
# The corpus is explicit that they stand on their own:
# nhm_corpus/antenatal_care.md, "Danger signs in pregnancy requiring
# immediate referral" -- "Severe headache with blurred vision, and
# convulsions, sit in this list because they are the presenting signs of
# imminent eclampsia -- they are urgent whatever the blood pressure
# reading happens to be."
#
# That sentence is why any of this exists. Nothing captured these at all
# before: ExtractedFields had no field for a reported symptom, so a
# report of severe headache with blurred vision alongside a normal BP
# came back LOW, over the words "no abnormal findings recorded". Not a
# miss -- an assurance. Found by tests/test_risk_conformance.py.


# A visit the classifier could not score at all. Distinct from LOW on
# purpose: LOW is a finding ("I read her vitals and they are normal"),
# this is the absence of one ("nothing came through"). Collapsing the two
# is how a failed transcription ends up looking like a healthy patient --
# the ASHA sees a calm green badge and an assurance that everything is
# within range, when in fact nothing was measured. A silent failure should
# read as louder than a normal result, not identical to it.
UNASSESSED = "UNASSESSED"


def has_clinical_signal(extracted: ExtractedFields) -> bool:
    """Did Agent 1 recover anything this classifier can actually score?

    Only the fields the rules below read count. A patient name and an age
    are not clinical signal: a transcript that yielded nothing but "Meera,
    28" tells you who the visit was about and nothing about how she is.

    medication_compliance == "unknown" is treated as absent for the same
    reason -- it is Agent 1 recording that it could not tell, which is not
    an observation. "compliant" does count, even though it scores zero:
    somebody said the iron tablets were being taken, and that is a real
    negative finding rather than a gap.
    """
    return any((
        extracted.bp_systolic is not None and extracted.bp_diastolic is not None,
        extracted.temperature_c is not None,
        extracted.blood_sugar_fasting is not None,
        extracted.blood_sugar_random is not None,
        extracted.medication_compliance in ("compliant", "non_compliant"),
        bool(extracted.violence_or_injury),
        bool(extracted.social_risk_factors),
        # What she reported is an observation too. Without this line a
        # visit whose only content was "severe headache and blurred
        # vision" came back UNASSESSED -- the danger sign discarded and
        # the ASHA asked to record the visit again.
        bool(extracted.danger_signs),
    ))


@dataclass
class RiskResult:
    risk_level: str  # HIGH | MEDIUM | LOW
    risk_score: float  # 0.0 - 1.0
    drivers: list[RiskDriver]


class NHMProtocolKnowledgeBase:
    def classify(self, extracted: ExtractedFields) -> RiskResult:
        if not has_clinical_signal(extracted):
            return RiskResult(
                risk_level=UNASSESSED,
                risk_score=0.0,
                drivers=[RiskDriver(
                    observation="No clinical observations were recovered from this visit",
                    reason=(
                        "Nothing in the recording could be read as a vital sign, a "
                        "medication answer, or a reported concern, so there is nothing "
                        "to assess against NHM thresholds. This is not a normal result "
                        "-- record the visit again, or enter the details by hand."
                    ),
                )],
            )

        drivers: list[RiskDriver] = []
        score = 0.0

        # First, and on their own terms. The corpus puts these on the
        # immediate-referral list and says they are urgent "whatever the
        # blood pressure reading happens to be", so a normal BP measured
        # on the same visit must not be allowed to average them away.
        for sign in extracted.danger_signs:
            drivers.append(RiskDriver(
                observation=f"Reported: {sign}",
                reason=(
                    "NHM antenatal care lists this under danger signs requiring "
                    "immediate referral to a first referral unit. These signs are "
                    "urgent whatever the blood pressure reading happens to be."
                ),
            ))
            score += 1.0

        if extracted.bp_systolic and extracted.bp_diastolic:
            bp = f"{extracted.bp_systolic}/{extracted.bp_diastolic}"
            if extracted.bp_systolic >= HIGH_BP_SYSTOLIC or extracted.bp_diastolic >= HIGH_BP_DIASTOLIC:
                drivers.append(RiskDriver(
                    observation=f"BP {bp}",
                    reason="BP at or above 140/90 meets NHM pre-eclampsia risk threshold for pregnant patients.",
                ))
                score += 0.5
            elif extracted.bp_systolic >= ELEVATED_BP_SYSTOLIC or extracted.bp_diastolic >= ELEVATED_BP_DIASTOLIC:
                drivers.append(RiskDriver(
                    observation=f"BP {bp}",
                    reason="BP is elevated above normal range; NHM protocol recommends closer monitoring.",
                ))
                score += 0.2

        if extracted.medication_compliance == "non_compliant":
            detail = extracted.medication_compliance_detail or "medication"
            drivers.append(RiskDriver(
                observation=f"Non-compliant: {detail}",
                reason="Missed iron/medication course increases anaemia and complication risk per NHM ANC protocol.",
            ))
            score += 0.25

        if extracted.temperature_c and extracted.temperature_c >= LOW_TEMP_FEVER_C:
            drivers.append(RiskDriver(
                observation=f"Temperature {extracted.temperature_c}C",
                reason="Fever during pregnancy requires prompt clinical evaluation per NHM protocol.",
            ))
            score += 0.3

        if extracted.blood_sugar_fasting is not None:
            value = extracted.blood_sugar_fasting
            if value >= HIGH_FASTING_SUGAR:
                drivers.append(RiskDriver(
                    observation=f"Fasting blood sugar {value} mg/dL",
                    reason=(
                        f"Fasting glucose at or above {HIGH_FASTING_SUGAR} mg/dL meets the "
                        "diabetes threshold; in pregnancy this needs prompt review for "
                        "gestational diabetes per NHM protocol."
                    ),
                ))
                score += 0.5
            elif value >= ELEVATED_FASTING_SUGAR:
                drivers.append(RiskDriver(
                    observation=f"Fasting blood sugar {value} mg/dL",
                    reason=(
                        f"Fasting glucose {ELEVATED_FASTING_SUGAR}-{HIGH_FASTING_SUGAR - 1} mg/dL is "
                        "impaired fasting glucose; NHM protocol recommends monitoring."
                    ),
                ))
                score += 0.2

        if extracted.blood_sugar_random is not None:
            value = extracted.blood_sugar_random
            if value >= HIGH_RANDOM_SUGAR:
                drivers.append(RiskDriver(
                    observation=f"Random blood sugar {value} mg/dL",
                    reason=(
                        f"Random glucose at or above {HIGH_RANDOM_SUGAR} mg/dL meets the diabetes "
                        "threshold and warrants facility referral per NHM protocol."
                    ),
                ))
                score += 0.5
            elif value >= ELEVATED_RANDOM_SUGAR:
                drivers.append(RiskDriver(
                    observation=f"Random blood sugar {value} mg/dL",
                    reason=(
                        f"Random glucose {ELEVATED_RANDOM_SUGAR}-{HIGH_RANDOM_SUGAR - 1} mg/dL is "
                        "above normal; NHM protocol recommends a confirmatory fasting test."
                    ),
                ))
                score += 0.2

        # Reported violence or injury escalates on its own. Unlike a vital
        # sign there's no "mildly assaulted" band to grade: the ASHA has
        # been told about or has seen harm, and the response is the same
        # urgent one whatever the other readings say.
        if extracted.violence_or_injury:
            drivers.append(RiskDriver(
                observation=", ".join(extracted.violence_or_injury).capitalize(),
                reason=(
                    "Reported violence or injury is a safety emergency requiring same-day "
                    "escalation and medical assessment, regardless of other vitals. NHM "
                    "guidance routes suspected domestic violence to the facility medical "
                    "officer."
                ),
            ))
            score += 1.0

        if extracted.social_risk_factors:
            drivers.append(RiskDriver(
                observation=", ".join(extracted.social_risk_factors),
                reason="Social isolation / absent support reduces likelihood of timely facility follow-up.",
            ))
            score += 0.15 * len(extracted.social_risk_factors)

        score = min(score, 1.0)
        if score >= 0.5:
            level = "HIGH"
        elif score >= 0.2:
            level = "MEDIUM"
        else:
            level = "LOW"

        if not drivers:
            # Reachable only when has_clinical_signal() was true, so this
            # really does mean "measured, and normal" rather than "silent".
            drivers.append(RiskDriver(
                observation="No abnormal findings recorded",
                reason="The observations recovered from this visit are within normal NHM range.",
            ))

        return RiskResult(risk_level=level, risk_score=round(score, 2), drivers=drivers)


def get_nhm_knowledge_base() -> NHMProtocolKnowledgeBase:
    return NHMProtocolKnowledgeBase()
