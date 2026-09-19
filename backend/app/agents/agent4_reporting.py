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


def build_rch_register(db: Session, worker_id: str, month: int, year: int) -> list[dict]:
    """FR-05.2: the RCH register itself -- one row per *patient* who had a
    maternal or under-5 visit in this period, with the fields a real
    register carries (her name, RCH number, category, ANC visit count,
    latest risk, last visit date). Not a count: a count is what this used
    to be (`rch_register_entries` incremented once per matching visit,
    with nothing behind it to look up), which satisfies nobody asking
    "which patients, and what's her status" -- the actual acceptance
    criterion (SRS FR-05.2: "auto-populated for all maternal patients").

    "RCH-eligible" mirrors build_visit_contribution's own definition
    (pregnant, or age < 5) so this register and the HMIS totals it feeds
    never disagree about who counts.
    """
    visits = (
        db.query(Visit)
        .filter(
            Visit.worker_id == worker_id,
            sql_extract("month", Visit.created_at) == month,
            sql_extract("year", Visit.created_at) == year,
        )
        .order_by(Visit.created_at)
        .all()
    )

    by_patient: dict[str, dict] = {}
    for v in visits:
        if not v.structured_json:
            continue
        extracted = json.loads(v.structured_json)
        pregnancy_stage = extracted.get("pregnancy_stage")
        age = extracted.get("age")
        is_maternal = bool(pregnancy_stage)
        is_child = age is not None and age < 5
        if not (is_maternal or is_child):
            continue
        entry = by_patient.setdefault(v.patient_id, {
            "patient_id": v.patient_id,
            "category": "maternal" if is_maternal else "child",
            "anc_visits": 0,
            "last_visit_at": None,
            "last_risk_level": None,
            "pregnancy_stage": None,
        })
        entry["anc_visits"] += 1
        entry["last_visit_at"] = v.created_at.isoformat()
        entry["last_risk_level"] = v.risk_level
        if pregnancy_stage:
            entry["pregnancy_stage"] = pregnancy_stage

    if not by_patient:
        return []

    patients = {p.patient_id: p for p in db.query(Patient).filter(Patient.patient_id.in_(by_patient.keys())).all()}
    register = []
    for patient_id, entry in by_patient.items():
        patient = patients.get(patient_id)
        register.append({
            **entry,
            "patient_name": patient.name if patient else "Unknown",
            "rch_number": patient.rch_number if patient else None,
            "village": patient.village if patient else None,
        })
    register.sort(key=lambda r: r["last_visit_at"] or "", reverse=True)
    return register


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
    non_compliance_count = 0
    for v in visits:
        if not v.structured_json:
            continue
        extracted = json.loads(v.structured_json)
        if extracted.get("pregnancy_stage"):
            anc_visits += 1
        if extracted.get("medication_compliance") == "non_compliant":
            non_compliance_count += 1

    unique_patients = len({v.patient_id for v in visits})
    rch_register = build_rch_register(db, worker_id, month, year)

    data = {
        "total_home_visits": total_visits,
        "unique_patients_visited": unique_patients,
        "anc_visits_recorded": anc_visits,
        # The count now comes from the register itself -- one row per
        # eligible patient -- instead of being tallied separately from a
        # slightly different rule (this used to count maternal visits
        # only, so it silently excluded every under-5 child).
        "rch_register_entries": len(rch_register),
        "rch_register": rch_register,
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
