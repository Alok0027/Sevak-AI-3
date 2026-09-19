"""GET /api/v1/reports/hmis/{worker_id}/{month}/{year} (FR-05.3)."""
import json
import os

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.agents import agent4_reporting as agent4
from app.api.deps import DbSession, require_roles, require_worker_access
from app.services.pdf_generator import generate_hmis_pdf

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.get("/hmis/{worker_id}/{month}/{year}")
def get_hmis_report(
    worker_id: str,
    month: int,
    year: int,
    db: DbSession,
    _user=Depends(require_roles("asha", "anm", "bmo", "admin")),
) -> dict:
    require_worker_access(_user, db, worker_id)
    report = agent4.regenerate_monthly_report(db, worker_id=worker_id, month=month, year=year)
    data = json.loads(report.data_json)

    pdf_path = generate_hmis_pdf(worker_id=worker_id, month=month, year=year, data=data)
    report.pdf_url = f"/api/v1/reports/hmis/{worker_id}/{month}/{year}/pdf"
    db.commit()

    return {"report_data_json": data, "pdf_url": report.pdf_url}


@router.get("/hmis/{worker_id}/{month}/{year}/pdf")
def download_hmis_pdf(
    worker_id: str,
    month: int,
    year: int,
    db: DbSession,
    _user=Depends(require_roles("asha", "anm", "bmo", "admin")),
):
    require_worker_access(_user, db, worker_id)
    report = agent4.regenerate_monthly_report(db, worker_id=worker_id, month=month, year=year)
    data = json.loads(report.data_json)
    pdf_path = generate_hmis_pdf(worker_id=worker_id, month=month, year=year, data=data)
    return FileResponse(pdf_path, media_type="application/pdf", filename=os.path.basename(pdf_path))
