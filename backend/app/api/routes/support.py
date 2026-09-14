"""The Help screen's "report a problem", and the Admin panel's view of it.

A support route is not usually worth its own module, but this one closes a
loop nothing else in the system closes. Every other signal the platform
collects is about a *patient*. This is the only one about the app itself
failing the person using it -- and the EOI deck's answer to "user adoption"
risk is exactly that: hear about it and fix it.

An ASHA posts; an admin reads and resolves. Deliberately not visible to her
ANM or BMO: "the microphone does not work" is a complaint about the tool,
and routing it to the supervisor who rates her performance is a good way to
make sure it never gets reported.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import aliased

from app.api.deps import DbSession, require_roles
from app.db.models.support_ticket import SupportTicket
from app.db.models.worker import Worker
from app.schemas.support import (
    CATEGORIES,
    SupportContact,
    SupportContactsResponse,
    SupportTicketCreate,
    SupportTicketListResponse,
    SupportTicketOut,
    SupportTicketResolveRequest,
)
from app.services.audit import record as audit_record

router = APIRouter(prefix="/api/v1/support", tags=["support"])

Reporter = aliased(Worker)


def _to_out(ticket: SupportTicket, worker: Worker | None) -> SupportTicketOut:
    return SupportTicketOut(
        ticket_id=ticket.ticket_id,
        worker_id=ticket.worker_id,
        worker_name=worker.name if worker else None,
        worker_phone=worker.phone if worker else None,
        sub_centre_id=worker.sub_centre_id if worker else None,
        category=ticket.category,
        message=ticket.message,
        app_version=ticket.app_version,
        device_info=ticket.device_info,
        language=ticket.language,
        status=ticket.status,
        created_at=ticket.created_at,
        resolved_at=ticket.resolved_at,
        resolution_note=ticket.resolution_note,
    )


@router.get("/contacts", response_model=SupportContactsResponse)
def my_contacts(
    db: DbSession,
    user=Depends(require_roles("asha", "anm", "bmo")),
) -> SupportContactsResponse:
    """Who this worker can actually ring when she is stuck.

    Returned from the server rather than typed into the app, because the
    ANM covering a sub-centre changes and a number hardcoded in a release
    is a number that is wrong within the year.

    Same rule the escalation agent uses (agent5._supervisor_for): her ANM
    if the sub-centre has one, and the block office either way -- an ASHA
    whose sub-centre has no ANM on record must still have somebody to call.
    """
    me = db.query(Worker).filter(Worker.worker_id == user.worker_id).first()
    if me is None:
        return SupportContactsResponse(contacts=[])

    contacts: list[SupportContact] = []
    if me.role == "asha" and me.sub_centre_id:
        anm = (
            db.query(Worker)
            .filter(Worker.role == "anm", Worker.sub_centre_id == me.sub_centre_id)
            .first()
        )
        if anm is not None:
            contacts.append(
                SupportContact(name=anm.name, phone=anm.phone, role=anm.role, relationship="anm")
            )

    bmo = db.query(Worker).filter(Worker.role == "bmo").first()
    if bmo is not None and bmo.worker_id != user.worker_id:
        contacts.append(
            SupportContact(name=bmo.name, phone=bmo.phone, role=bmo.role, relationship="block_office")
        )
    return SupportContactsResponse(contacts=contacts)


@router.post("/tickets", response_model=SupportTicketOut, status_code=201)
def create_ticket(
    payload: SupportTicketCreate,
    db: DbSession,
    user=Depends(require_roles("asha", "anm", "bmo")),
) -> SupportTicketOut:
    """Report a problem with the app.

    Open to supervisors too, not just ASHAs: an ANM whose dashboard will not
    load has the same problem and the same nowhere to put it.
    """
    category = payload.category.strip().lower()
    if category not in CATEGORIES:
        # Not a 400. A future app build offering a new category must not have
        # its tickets rejected by an older server -- losing the report is a
        # worse outcome than filing it under "other".
        category = "other"

    ticket = SupportTicket(
        worker_id=user.worker_id,
        category=category,
        message=payload.message.strip(),
        app_version=payload.app_version,
        device_info=payload.device_info,
        language=payload.language,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    audit_record(
        db,
        user_id=user.worker_id,
        action_type="support.ticket_created",
        record_id=ticket.ticket_id,
        record_type="support_ticket",
        details={"category": category},
    )

    worker = db.query(Worker).filter(Worker.worker_id == user.worker_id).first()
    return _to_out(ticket, worker)


@router.get("/tickets/mine", response_model=SupportTicketListResponse)
def my_tickets(
    db: DbSession,
    user=Depends(require_roles("asha", "anm", "bmo")),
) -> SupportTicketListResponse:
    """What she reported, and whether anybody answered.

    Without this the Help screen is a suggestion box with no lid and no
    bottom: she types into it once, hears nothing, and never uses it again.
    """
    rows = (
        db.query(SupportTicket)
        .filter(SupportTicket.worker_id == user.worker_id)
        .order_by(SupportTicket.created_at.desc())
        .all()
    )
    worker = db.query(Worker).filter(Worker.worker_id == user.worker_id).first()
    return SupportTicketListResponse(
        tickets=[_to_out(t, worker) for t in rows],
        open_count=sum(1 for t in rows if t.status == "open"),
    )


@router.get("/tickets", response_model=SupportTicketListResponse)
def list_tickets(
    db: DbSession,
    _user=Depends(require_roles("admin")),
    status_filter: str | None = Query(default=None, alias="status", description="open | resolved"),
) -> SupportTicketListResponse:
    query = db.query(SupportTicket, Reporter).outerjoin(
        Reporter, Reporter.worker_id == SupportTicket.worker_id
    )
    if status_filter:
        query = query.filter(SupportTicket.status == status_filter.strip().lower())
    rows = query.order_by(SupportTicket.created_at.desc()).all()

    open_count = (
        db.query(SupportTicket).filter(SupportTicket.status == "open").count()
    )
    return SupportTicketListResponse(
        tickets=[_to_out(t, w) for t, w in rows],
        open_count=open_count,
    )


@router.post("/tickets/{ticket_id}/resolve", response_model=SupportTicketOut)
def resolve_ticket(
    ticket_id: str,
    payload: SupportTicketResolveRequest,
    db: DbSession,
    user=Depends(require_roles("admin")),
) -> SupportTicketOut:
    ticket = db.query(SupportTicket).filter(SupportTicket.ticket_id == ticket_id).first()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.status == "resolved":
        raise HTTPException(status_code=400, detail="Ticket is already resolved")

    ticket.status = "resolved"
    ticket.resolved_at = datetime.now(timezone.utc)
    ticket.resolved_by = user.worker_id
    ticket.resolution_note = payload.note.strip()
    db.commit()

    audit_record(
        db,
        user_id=user.worker_id,
        action_type="support.ticket_resolved",
        record_id=ticket_id,
        record_type="support_ticket",
        details={"note": ticket.resolution_note},
    )

    worker = db.query(Worker).filter(Worker.worker_id == ticket.worker_id).first()
    return _to_out(ticket, worker)
