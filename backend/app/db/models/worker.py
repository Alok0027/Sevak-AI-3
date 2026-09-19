import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Worker(Base):
    """SRS section 6: workers table. Covers all 4 roles (FR-08 / table 4):
    asha, anm, bmo, admin. `role` gates permissions in app/api/deps.py."""

    __tablename__ = "workers"

    worker_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    pin_hash: Mapped[str] = mapped_column(String, nullable=False)
    language_pref: Mapped[str] = mapped_column(String, default="hi")  # ISO-ish code: hi, mr, ta, te, bn
    sub_centre_id: Mapped[str] = mapped_column(String, nullable=True)

    # The district this worker belongs to ("PUNE"), and the unit a BMO is
    # scoped to (SRS table 4: a BMO oversees multiple sub-centres in one
    # district; an ANM is scoped tighter, to her own sub_centre_id).
    #
    # Derived from sub_centre_id by identity.district_code() for anyone
    # who has one, and set directly for a BMO, who supervises a district
    # without being posted to a single sub-centre within it. Filled in by
    # the backfill in app/db/session.py for rows that predate the column.
    #
    # Nullable in the schema, never optional in effect: deps.py fails a
    # supervisor closed when it is missing rather than falling back to
    # "every district", which is what this column exists to prevent.
    district_id: Mapped[str] = mapped_column(String, nullable=True, index=True)
    role: Mapped[str] = mapped_column(String, default="asha")  # asha | anm | bmo | admin

    # The identifier a person can read aloud: ASHA-PUNE-01-007.
    #
    # A worker_id is a UUID, which is right for a foreign key and useless
    # on a referral slip or in a block meeting. Generated on creation from
    # role and sub-centre (app/services/identity.py) and never reissued --
    # it appears on paperwork, so a code that changed would make last
    # month's forms refer to nobody.
    #
    # Nullable because the column arrived on tables that already had rows;
    # those are filled in by the backfill in app/db/session.py.
    worker_code: Mapped[str] = mapped_column(String, unique=True, nullable=True, index=True)

    # pending | active | rejected. Gates login (app/api/routes/auth.py).
    #
    # Defaults to "active", which is the opposite of what fail-closed would
    # suggest, and is deliberate. Every path that builds a Worker today is
    # a trusted one -- the seeder, and an Admin using the staff panel -- so
    # defaulting to "pending" would lock every account in an existing
    # database out the moment this column appeared, including the admin
    # account needed to unlock them. Self-registration is the one untrusted
    # path, and it sets "pending" explicitly.
    #
    # If you add another way to create a Worker out of something a stranger
    # typed, set status="pending" on it. The check that actually protects
    # the system lives in login(), because that is the only door.
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default="active"
    )

    # Who let her in, and when. Approving an account is a decision a person
    # made about a stranger's claim to be a health worker; that belongs on
    # the record itself, not only in the audit log.
    approved_by: Mapped[str] = mapped_column(String, nullable=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
