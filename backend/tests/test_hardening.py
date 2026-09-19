"""Regression tests for account revocation, resource scope and sync receipts."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db.models.worker import Worker
from app.db.session import SessionLocal
from app.main import app


def worker(role="asha", centre="TEST-HARDENING"):
    worker_id = str(uuid4())
    with SessionLocal() as db:
        db.add(Worker(worker_id=worker_id, name="Hardening test",
                      phone=worker_id, pin_hash="unused", role=role,
                      sub_centre_id=centre, status="active"))
        db.commit()
    return worker_id, {"Authorization": f"Bearer {create_access_token(worker_id, role)}"}


@pytest.mark.parametrize("path", [
    "/patients/{worker}", "/tasks/{worker}",
    "/reports/hmis/{worker}/9/2026", "/reports/hmis/{worker}/9/2026/pdf",
])
def test_asha_cannot_read_another_workers_resources(path):
    _, headers = worker()
    other, _ = worker()
    with TestClient(app) as client:
        assert client.get("/api/v1" + path.format(worker=other), headers=headers).status_code == 403


@pytest.mark.parametrize("centre", [None, "", "   "])
def test_unassigned_anm_is_not_district_wide(centre):
    _, headers = worker("anm", centre)
    with TestClient(app) as client:
        assert client.get("/api/v1/patients", headers=headers).status_code == 403


def test_existing_token_respects_account_revocation_and_current_role():
    worker_id, headers = worker("bmo")
    with TestClient(app) as client:
        with SessionLocal() as db:
            db.get(Worker, worker_id).role = "asha"
            db.commit()
        assert client.get("/api/v1/dashboard/metrics", headers=headers).status_code == 403
        with SessionLocal() as db:
            db.get(Worker, worker_id).status = "rejected"
            db.commit()
        assert client.get(f"/api/v1/patients/{worker_id}", headers=headers).status_code == 401


def test_sync_rejects_worker_spoofing():
    _, headers = worker()
    other, _ = worker()
    with TestClient(app) as client:
        response = client.post("/api/v1/sync/batch", headers=headers,
                               json={"worker_id": other, "records": []})
        assert response.status_code == 403


def test_partial_sync_receipts_keep_original_indices_after_sorting():
    worker_id, headers = worker()
    with TestClient(app) as client:
        response = client.post("/api/v1/sync/batch", headers=headers, json={
            "worker_id": worker_id, "records": [
                {"record_type": "unknown"},
                {"record_type": "patient", "patient_id": str(uuid4()), "name": "Test only"},
            ],
        })
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["synced"] == 1
        assert result["failed"] == 1
        assert {r["index"]: r["status"] for r in result["results"]} == {0: "failed", 1: "synced"}


def test_batch_size_is_bounded():
    worker_id, headers = worker()
    with TestClient(app) as client:
        assert client.post("/api/v1/sync/batch", headers=headers, json={
            "worker_id": worker_id, "records": [{}] * 101,
        }).status_code == 422
