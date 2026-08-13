"""Strict local schemas for untrusted model output."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ClassificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["EVENT", "TASK", "IRRELEVANT", "NEEDS_REVIEW"]
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=500)
    temporal_ambiguity: bool

    @field_validator("kind", mode="before")
    @classmethod
    def normalize_kind(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["EVENT", "TASK"]
    title: str = Field(min_length=1, max_length=300)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    deadline: datetime | None = None
    timezone: str = Field(min_length=1, max_length=80)
    location: str | None = Field(default=None, max_length=300)
    participants: tuple[str, ...] = Field(default=(), max_length=30)
    estimated_duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    priority: Literal["LOW", "NORMAL", "HIGH"] | None = None
    allowed_windows: tuple[str, ...] = Field(default=(), max_length=10)
    confidence: float = Field(ge=0, le=1)
    assumptions: tuple[str, ...] = Field(default=(), max_length=10)
    evidence: tuple[str, ...] = Field(min_length=1, max_length=10)

    @field_validator("kind", "priority", mode="before")
    @classmethod
    def normalize_enums(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.upper()
        return "NORMAL" if normalized == "MEDIUM" else normalized

    @model_validator(mode="after")
    def validate_kind_fields(self) -> "ExtractionOutput":
        if self.kind == "EVENT":
            if self.starts_at is None:
                raise ValueError("Event output requires starts_at")
            if self.deadline is not None:
                raise ValueError("Event output cannot include deadline")
        if self.kind == "TASK" and (self.starts_at is not None or self.ends_at is not None):
            raise ValueError("Task output cannot include an execution slot")
        return self
