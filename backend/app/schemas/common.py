from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class IdResponse(BaseModel):
    id: UUID


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str
    timestamp: datetime
