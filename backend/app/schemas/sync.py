from typing import Any

from pydantic import BaseModel


class SyncBatchRequest(BaseModel):
    worker_id: str
    records: list[dict[str, Any]]


class SyncBatchResponse(BaseModel):
    synced: int
    failed: int
    errors: list[str] = []
