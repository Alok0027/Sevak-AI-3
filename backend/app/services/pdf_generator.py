"""Renders an HMIS-format PDF from an HMIS report's data_json (FR-05.3)."""
import json
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "generated_reports")


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

    rows = [["Field", "Value"]] + [[str(k), str(v)] for k, v in data.items()]
    table = Table(rows, colWidths=[80 * mm, 80 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f6f4a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    return filepath


def load_report_json(data_json: str) -> dict:
    return json.loads(data_json)
