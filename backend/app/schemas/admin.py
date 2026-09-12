"""Admin panel: district-wide staff directory + audit trail viewer.

Not in the SRS's original table 19 -- added because an 'admin' role already
existed in RBAC (app/db/models/worker.py) with nowhere to actually manage
staff or review NFR-SC4's audit log. list_workers/worker_history in
app/api/routes/workers.py deliberately only ever return ASHA workers (the
roster is a clinical-performance view); this is the district-wide staff
list across all four roles, plus account creation and the audit trail."""
from datetime import datetime

from pydantic import BaseModel, field_validator

VALID_ROLES = ("asha", "anm", "bmo", "admin")


class StaffMember(BaseModel):
    worker_id: str
    name: str
    phone: str
    role: str
    sub_centre_id: str | None
    language_pref: str
    created_at: datetime


class StaffListResponse(BaseModel):
    staff: list[StaffMember]


class StaffCreateRequest(BaseModel):
    name: str
    phone: str
    pin: str
    role: str
    sub_centre_id: str | None = None
    language_pref: str = "hi"

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of {VALID_ROLES}")
        return v

    @field_validator("pin")
    @classmethod
    def _pin_shape(cls, v: str) -> str:
        if not v.isdigit() or not (4 <= len(v) <= 6):
            raise ValueError("pin must be 4-6 digits")
        return v

    @field_validator("name", "phone")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class AuditLogEntry(BaseModel):
    log_id: str
    user_id: str
    actor_name: str | None
    actor_role: str | None
    action_type: str
    record_id: str | None
    record_type: str | None
    timestamp: datetime
    ip_address: str | None
    details: dict | None


class AuditLogResponse(BaseModel):
    entries: list[AuditLogEntry]
