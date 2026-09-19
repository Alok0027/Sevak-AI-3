"""Renders an HMIS-format PDF from an HMIS report's data_json (FR-05.3)."""
import json
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "generated_reports")


_TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f6f4a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
    ]
)


def generate_hmis_pdf(worker_id: str, month: int, year: int, data: dict) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = f"hmis_{worker_id}_{year}_{month:02d}.pdf"
    filepath = os.path.join(REPORTS_DIR, filename)

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(filepath, pagesize=A4, topMargin=20 * mm)
    story = [
        Paragraph("Health Management Information System (HMIS) -- Monthly Report", styles["Title"]),
        Spacer(1, 6 * mm),
        Paragraph(f"Worker ID: {worker_id}  |  Period: {month:02d}/{year}", styles["Normal"]),
        Spacer(1, 8 * mm),
    ]

    # FR-05.2's register is a list of per-patient dicts, not a summary
    # figure -- it gets its own table below, not a `str(v)` dump into this
    # one (which would print a Python repr of the list into a PDF cell).
    summary = {k: v for k, v in data.items() if k != "rch_register"}
    rows = [["Field", "Value"]] + [[str(k), str(v)] for k, v in summary.items()]
    table = Table(rows, colWidths=[80 * mm, 80 * mm])
    table.setStyle(_TABLE_STYLE)
    story.append(table)

    register = data.get("rch_register") or []
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph("RCH Register -- maternal &amp; under-5 patients visited this month", styles["Heading2"]))
    story.append(Spacer(1, 3 * mm))
    if register:
        reg_rows = [["Patient", "RCH No.", "Category", "Village", "ANC Visits", "Last Risk", "Last Visit"]]
        for r in register:
            reg_rows.append([
                r.get("patient_name") or "Unknown",
                r.get("rch_number") or "—",
                (r.get("category") or "").capitalize(),
                r.get("village") or "—",
                str(r.get("anc_visits") or 0),
                r.get("last_risk_level") or "—",
                (r.get("last_visit_at") or "")[:10],
            ])
        reg_table = Table(reg_rows, colWidths=[30 * mm, 26 * mm, 18 * mm, 20 * mm, 20 * mm, 18 * mm, 24 * mm])
        reg_table.setStyle(_TABLE_STYLE)
        story.append(reg_table)
    else:
        story.append(Paragraph("No maternal or under-5 visits recorded this month.", styles["Normal"]))

    doc.build(story)
    return filepath


def load_report_json(data_json: str) -> dict:
    return json.loads(data_json)
