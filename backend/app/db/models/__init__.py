"""Importing this package registers every model on Base.metadata.

Both `init_db()` and Alembic's `env.py` need the full set: create_all only
creates tables it can see, and autogenerate will propose *dropping* a table
whose model nobody imported. Keeping the list here means the two cannot
drift apart, which they did while each maintained its own copy.
"""
from app.db.models import (  # noqa: F401
    absence,
    action,
    audit_log,
    correction_document,
    hmis_report,
    notification,
    patient,
    risk_flag,
    risk_resolution,
    support_ticket,
    sync_queue,
    visit,
    visit_request,
    worker,
)
