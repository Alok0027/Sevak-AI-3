from typing import Any

from pydantic import BaseModel, Field


class SyncBatchRequest(BaseModel):
    worker_id: str
    records: list[dict[str, Any]] = Field(max_length=100)


class SyncBatchResponse(BaseModel):
    synced: int
    failed: int
    errors: list[str] = Field(default_factory=list)
    results: list[dict[str, Any]] = Field(default_factory=list)
