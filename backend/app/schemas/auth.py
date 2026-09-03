from pydantic import BaseModel


class LoginRequest(BaseModel):
    phone: str
    pin: str


class LoginResponse(BaseModel):
    access_token: str
    role: str
    worker_id: str
    worker_name: str
