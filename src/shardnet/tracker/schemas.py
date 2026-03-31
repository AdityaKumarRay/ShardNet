"""Tracker API response schemas."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str


class MetaResponse(BaseModel):
    api_version: str
    protocol_version: int
    service: str
