from pydantic import BaseModel, Field, field_validator

# Admin is not here on purpose. It is the role that creates every other
# account and reads the audit log; a system where anyone can register as
# one has no access control at all, only the appearance of it. The first
# admin comes from the bootstrap (scripts/bootstrap_admin.py), and every
# one after that is created by an existing admin.
SELF_REGISTERABLE_ROLES = ("asha", "anm", "bmo")

PIN_LENGTH = 4


def _validate_pin(value: str) -> str:
    value = value.strip()
    if not value.isdigit() or len(value) != PIN_LENGTH:
        raise ValueError(f"PIN must be exactly {PIN_LENGTH} digits")
    return value


class LoginRequest(BaseModel):
    phone: str
    pin: str


class LoginResponse(BaseModel):
    access_token: str
    role: str
    worker_id: str
    worker_name: str


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    # Ten digits, as an Indian mobile number is written and as she would
    # read one out. Validated because this is the field an admin will use
    # to ring her back and check she is who she says she is -- a typo here
    # makes the account unapprovable.
    phone: str = Field(min_length=10, max_length=15)
    pin: str
    role: str = "asha"
    sub_centre_id: str | None = None
    language_pref: str = "hi"

    @field_validator("phone")
    @classmethod
    def _digits_only(cls, v: str) -> str:
        v = "".join(ch for ch in v if ch.isdigit())
        if len(v) != 10:
            raise ValueError("phone must be 10 digits")
        return v

    @field_validator("pin")
    @classmethod
    def _pin_shape(cls, v: str) -> str:
        return _validate_pin(v)

    @field_validator("role")
    @classmethod
    def _registerable_role(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in SELF_REGISTERABLE_ROLES:
            raise ValueError(f"role must be one of {SELF_REGISTERABLE_ROLES}")
        return v


class RegisterResponse(BaseModel):
    """Deliberately carries no token.

    Registering is a request, not an arrival. Returning an access token
    here -- even a limited one -- would mean a stranger who filled in a
    form is holding a credential for a health system, which is the whole
    thing this flow exists to prevent.
    """

    worker_id: str
    name: str
    phone: str
    role: str
    status: str


class ChangePinRequest(BaseModel):
    current_pin: str
    new_pin: str

    @field_validator("current_pin", "new_pin")
    @classmethod
    def _pin_shape(cls, v: str) -> str:
        return _validate_pin(v)
