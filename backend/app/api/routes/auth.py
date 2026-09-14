"""Sign-in, sign-up, and PIN change.

POST /login is SRS table 19. /register and /change-pin are not in the SRS
and were added deliberately:

  * /register, because SRS table 4 gives worker onboarding to the Admin
    panel and nothing else -- which is correct, but left no answer to
    "how does a new ASHA get an account at all". She registers; an admin
    approves. She is not signed up by filling in a form, and she is not
    waiting on somebody to type her details either.

  * /change-pin, because an admin who sets a worker's PIN knows it, and
    she had no way to change it. That is worse than any gap in the
    registration flow.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import CurrentUser, DbSession, get_current_user
from app.core.security import create_access_token, hash_pin, verify_pin
from app.db.models.worker import Worker
from app.schemas.auth import (
    ChangePinRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
)
from app.services.audit import record as audit_record

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: DbSession, request: Request) -> LoginResponse:
    # NFR-SC4: audit trail for every data access -- logins included, with
    # the caller's IP so an admin reviewing the trail can spot a run of
    # failed attempts from somewhere unexpected.
    ip_address = request.client.host if request.client else None
    worker = db.query(Worker).filter(Worker.phone == payload.phone).first()
    if worker is None or not verify_pin(payload.pin, worker.pin_hash):
        audit_record(
            db,
            user_id=worker.worker_id if worker else payload.phone,
            action_type="auth.login_failed",
            record_type="worker",
            ip_address=ip_address,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid phone or PIN")

    # The one door. Every other guard in the system checks a token, and a
    # token only ever comes from here or /refresh -- so this is the single
    # place where "has a person approved this account" has to be true.
    #
    # Told apart from a wrong PIN on purpose. "Invalid phone or PIN" to
    # somebody whose registration is simply unapproved sends her to ring
    # the block office about a password she typed correctly.
    if worker.status != "active":
        audit_record(
            db,
            user_id=worker.worker_id,
            action_type="auth.login_blocked",
            record_id=worker.worker_id,
            record_type="worker",
            ip_address=ip_address,
            details={"status": worker.status},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Your registration is waiting for approval."
                if worker.status == "pending"
                else "This account is not active. Contact your block office."
            ),
        )

    token = create_access_token(subject=worker.worker_id, role=worker.role)
    audit_record(
        db,
        user_id=worker.worker_id,
        action_type="auth.login",
        record_id=worker.worker_id,
        record_type="worker",
        ip_address=ip_address,
    )
    return LoginResponse(
        access_token=token, role=worker.role, worker_id=worker.worker_id, worker_name=worker.name
    )


@router.post("/refresh", response_model=LoginResponse)
def refresh(
    db: DbSession,
    user: CurrentUser = Depends(get_current_user),
) -> LoginResponse:
    """Trade a still-valid token for a fresh one.

    The app calls this whenever it starts with signal. That is what makes
    the long field token safe to hand out: a worker who opens the app even
    once a month never runs the clock down, so the only stale token in
    existence belongs to a phone that is both lost and switched off.

    Deliberately has no separate refresh-token mechanism. A refresh token
    the app would have to store beside the access token is one more secret
    on a device that may be shared in a village, for no gain here -- if the
    access token is valid, its holder is already authenticated.
    """
    worker = db.query(Worker).filter(Worker.worker_id == user.worker_id).first()
    if worker is None:
        # The account was deleted or renamed away while the token was still
        # in date. Fail closed rather than minting a new token for a worker
        # who no longer exists.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker no longer exists")
    # An account revoked while she held a live token must not be able to
    # renew it. Field tokens last 30 days, so without this check a revoked
    # ASHA would keep extending her own access for as long as she kept
    # opening the app.
    if worker.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is not active")

    audit_record(
        db,
        user_id=worker.worker_id,
        action_type="auth.refresh",
        record_id=worker.worker_id,
        record_type="worker",
    )
    return LoginResponse(
        access_token=create_access_token(subject=worker.worker_id, role=worker.role),
        role=worker.role,
        worker_id=worker.worker_id,
        worker_name=worker.name,
    )


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(payload: RegisterRequest, db: DbSession, request: Request) -> RegisterResponse:
    """Ask for an account. An admin decides whether you get one.

    The account row is created immediately but with status="pending", and
    login() refuses it until a person approves. So this endpoint being open
    to the internet gives a stranger exactly one thing: a row in a queue an
    admin reads.

    That is the honest shape of onboarding a government health worker. She
    is appointed to an ASHA post by someone; the app should check that
    somebody says so, and the cheapest reliable check is a human who can
    ring the number she typed. No token is returned -- see RegisterResponse.
    """
    ip_address = request.client.host if request.client else None

    existing = db.query(Worker).filter(Worker.phone == payload.phone).first()
    if existing is not None:
        # Says "taken", never "taken by an ANM in Wagholi". A registration
        # form open to anyone is also a way to ask the system which phone
        # numbers belong to health workers.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account already exists for this phone number.",
        )

    worker = Worker(
        name=payload.name.strip(),
        phone=payload.phone,
        pin_hash=hash_pin(payload.pin),
        role=payload.role,
        sub_centre_id=payload.sub_centre_id.strip() if payload.sub_centre_id else None,
        language_pref=payload.language_pref,
        status="pending",
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)

    audit_record(
        db,
        user_id=worker.worker_id,
        action_type="auth.register",
        record_id=worker.worker_id,
        record_type="worker",
        ip_address=ip_address,
        details={"role": worker.role, "sub_centre_id": worker.sub_centre_id},
    )
    return RegisterResponse(
        worker_id=worker.worker_id,
        name=worker.name,
        phone=worker.phone,
        role=worker.role,
        status=worker.status,
    )


@router.post("/change-pin", status_code=204)
def change_pin(
    payload: ChangePinRequest,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Change your own PIN. Requires the current one.

    Every account in this system starts with a PIN somebody else chose --
    an admin creating staff, or a default handed out at a block meeting.
    Until now there was no way to change it, so "her" PIN was permanently
    known to whoever set it, and shared PINs at a sub-centre had no way of
    ever being unshared.

    Requiring the current PIN is what stops this being a way to take over
    an account from an unlocked phone.
    """
    ip_address = request.client.host if request.client else None
    worker = db.query(Worker).filter(Worker.worker_id == user.worker_id).first()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker no longer exists")

    if not verify_pin(payload.current_pin, worker.pin_hash):
        audit_record(
            db,
            user_id=worker.worker_id,
            action_type="auth.change_pin_failed",
            record_id=worker.worker_id,
            record_type="worker",
            ip_address=ip_address,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Current PIN is wrong")

    if payload.new_pin == payload.current_pin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That is your current PIN")

    worker.pin_hash = hash_pin(payload.new_pin)
    db.commit()

    # The new PIN is not in the audit entry, and must never be: the audit
    # log is readable by every admin, which would make "change your PIN"
    # a way of publishing it to them.
    audit_record(
        db,
        user_id=worker.worker_id,
        action_type="auth.change_pin",
        record_id=worker.worker_id,
        record_type="worker",
        ip_address=ip_address,
    )
