import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class WorkerAbsence(Base):
    """An ASHA is away, and a named colleague is covering her patients.

    Cover, deliberately -- not a transfer.

    A transfer is what happens when somebody leaves the post: ownership
    moves, a supervisor decides, and it does not come back. That already
    exists (POST /patients/caseload/{id}/reassign) and is correctly
    restricted to an ANM.

    Going away for a fortnight is a different thing entirely, and modelling
    it as a transfer would be wrong in three ways at once. Her patients
    would stop being hers, so she would come back to an empty list and have
    to ask somebody to give her own village back. The colleague would find
    forty women on her list with no record of why or for how long. And
    because a transfer needs a supervisor, an ASHA leaving on Friday would
    need her ANM to be at a desk on Friday -- which is exactly the kind of
    dependency that makes people stop telling anyone they are going away.

    So: ownership does not move. The covering worker gains sight of the
    patients and the ability to record visits for them, for a stated
    window, and it lapses on its own. That makes it safe to let the ASHA
    arrange it herself, which is the whole point -- the alternative is she
    tells a colleague verbally and the system never knows, which is what
    happens today.

    A visit recorded during cover is stored against whoever actually made
    it. The covering ASHA walked to that house; the record should say so.
    """

    __tablename__ = "worker_absences"

    absence_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)

    # Who is away.
    worker_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # Who is looking after her patients while she is.
    covering_worker_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Dates, not timestamps. Leave is counted in days by everybody who
    # talks about it, and an ASHA picking an hour would be answering a
    # question nobody asked.
    starts_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    reason: Mapped[str] = mapped_column(Text, nullable=True)

    # Set when she comes back early and ends it herself. The row is kept
    # rather than deleted: who covered which village in March is a fact
    # somebody may need in April, and a deleted row answers nothing.
    ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    # Usually herself. An ANM can also arrange cover for a worker who is
    # already away and did not get the chance to.
    created_by: Mapped[str] = mapped_column(String, nullable=True)
