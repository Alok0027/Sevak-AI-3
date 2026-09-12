"""
NHM protocol knowledge base for Agent 2 risk classification (FR-03.1, FR-03.2).

This is a rule-based stand-in for the real RAG pipeline the SRS specifies
(ChromaDB vector store over >=20 NHM protocol documents, section 10 Week 2).
The rules below encode the same maternal/child-health thresholds a first
ChromaDB corpus would surface, so Agent 2's *output shape* (risk level +
explainable drivers) is already correct -- swapping the body of
`classify` for an embedding search + LLM reasoning call is a contained
change that doesn't touch any caller.

TODO (Week 2, per SRS section 10): replace this module's body with:
  1. Embed >=20 NHM protocol documents into ChromaDB.
  2. On classify(), retrieve top-k relevant protocol chunks for the
     extracted observations.
  3. Pass chunks + observations to the LLM client for a grounded
     HIGH/MEDIUM/LOW judgement with cited drivers.
Keep the function signature identical so agent2 doesn't need to change.
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


@dataclass
class RiskResult:
    risk_level: str  # HIGH | MEDIUM | LOW
    risk_score: float  # 0.0 - 1.0
    drivers: list[RiskDriver]


class NHMProtocolKnowledgeBase:
    def classify(self, extracted: ExtractedFields) -> RiskResult:
        drivers: list[RiskDriver] = []
        score = 0.0

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
            drivers.append(RiskDriver(
                observation="No abnormal findings recorded",
                reason="All extracted vitals and compliance signals are within normal NHM range.",
            ))

        return RiskResult(risk_level=level, risk_score=round(score, 2), drivers=drivers)


def get_nhm_knowledge_base() -> NHMProtocolKnowledgeBase:
    return NHMProtocolKnowledgeBase()
