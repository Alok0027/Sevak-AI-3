"""Agent 4 -- Reporting (FR-05): auto-populate HMIS/RCH fields from visit
data with zero manual entry, and keep the current month's report current
in near-real-time as each visit lands (matches the demo script's "Agent 4
is updating the HMIS report... all simultaneously")."""
import json
from datetime import datetime, timezone

from sqlalchemy import extract as sql_extract
from sqlalchemy.orm import Session

from app.db.models.hmis_report import HmisReport
from app.db.models.patient import Patient
from app.db.models.visit import Visit
from app.schemas.visit import ExtractedFields


def build_visit_contribution(extracted: ExtractedFields, risk_level: str) -> dict:
    """This visit's row-level contribution to the monthly HMIS/RCH figures."""
    return {
        "anc_visit_recorded": bool(extracted.pregnancy_stage),
        "bp_recorded": extracted.bp_systolic is not None,
        "high_risk_flagged": risk_level == "HIGH",
        "medication_non_compliance": extracted.medication_compliance == "non_compliant",
        "rch_eligible": bool(extracted.pregnancy_stage) or (extracted.age is not None and extracted.age < 5),
    }


def regenerate_monthly_report(db: Session, worker_id: str, month: int, year: int) -> HmisReport:
    """Aggregate every visit this worker recorded in (month, year) into the
    HMIS-format monthly totals (FR-05.1) and RCH register fields (FR-05.2).
    Called after every visit so the report is always current, and again
    on-demand by GET /reports/hmis/{worker_id}/{month}/{year}."""
    visits = (
        db.query(Visit)
        .filter(
            Visit.worker_id == worker_id,
            sql_extract("month", Visit.created_at) == month,
            sql_extract("year", Visit.created_at) == year,
        )
        .all()
    )

    total_visits = len(visits)
    high_risk = sum(1 for v in visits if v.risk_level == "HIGH")
    medium_risk = sum(1 for v in visits if v.risk_level == "MEDIUM")
    low_risk = sum(1 for v in visits if v.risk_level == "LOW")
    # Counted, not folded into low_risk. An HMIS return where the three
    # tiers do not add up to total_visits is a question somebody asks;
    # one where unassessed visits were quietly filed as LOW is a claim
    # that patients were assessed and found well when they were not.
    unassessed = sum(1 for v in visits if v.risk_level == "UNASSESSED")

    anc_visits = 0
    rch_entries = 0
    non_compliance_count = 0
    for v in visits:
        if not v.structured_json:
            continue
        extracted = json.loads(v.structured_json)
        if extracted.get("pregnancy_stage"):
            anc_visits += 1
            rch_entries += 1
        if extracted.get("medication_compliance") == "non_compliant":
            non_compliance_count += 1

    unique_patients = len({v.patient_id for v in visits})

    data = {
        "total_home_visits": total_visits,
        "unique_patients_visited": unique_patients,
        "anc_visits_recorded": anc_visits,
        "rch_register_entries": rch_entries,
        "high_risk_cases": high_risk,
        "medium_risk_cases": medium_risk,
        "low_risk_cases": low_risk,
        "unassessed_visits": unassessed,
        "medication_non_compliance_cases": non_compliance_count,
        "report_generated_at": datetime.now(timezone.utc).isoformat(),
    }

    report = (
        db.query(HmisReport)
        .filter(HmisReport.worker_id == worker_id, HmisReport.month == month, HmisReport.year == year)
        .first()
    )
    if report is None:
        report = HmisReport(worker_id=worker_id, month=month, year=year, data_json=json.dumps(data))
        db.add(report)
    else:
        report.data_json = json.dumps(data)
        report.generated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(report)
    return report
