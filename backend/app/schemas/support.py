"""Schemas for the Help screen's "report a problem" flow."""
from datetime import datetime

from pydantic import BaseModel, Field

# The fixed list the app offers her as buttons. Free text is still the
# message; this is only so the panel can group and count without anyone
# reading every ticket.
CATEGORIES = ("microphone", "transcription", "sync", "login", "risk", "other")


class SupportTicketCreate(BaseModel):
    category: str = Field(default="other")
    message: str = Field(min_length=3, max_length=2000)
    app_version: str | None = None
    device_info: str | None = None
    language: str | None = None


class SupportTicketOut(BaseModel):
    ticket_id: str
    worker_id: str
    worker_name: str | None = None
    worker_phone: str | None = None
    sub_centre_id: str | None = None
    category: str
    message: str
    app_version: str | None = None
    device_info: str | None = None
    language: str | None = None
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class SupportTicketListResponse(BaseModel):
    tickets: list[SupportTicketOut]
    open_count: int


class SupportContact(BaseModel):
    name: str
    phone: str
    role: str
    # "Your ANM" vs "Block office" -- which is which matters to her, and the
    # app should not have to infer it from the role string.
    relationship: str


class SupportContactsResponse(BaseModel):
    contacts: list[SupportContact]


class SupportTicketResolveRequest(BaseModel):
    # Required, and not trivially satisfiable: "done" tells the next person
    # nothing, and these tickets are the only record of what the app does to
    # people in the field.
    note: str = Field(min_length=5, max_length=2000)
