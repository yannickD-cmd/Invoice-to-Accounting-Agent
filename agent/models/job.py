"""Pydantic models for job state tracking."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    RECEIVED = "RECEIVED"
    EXTRACTING = "EXTRACTING"
    ENRICHING = "ENRICHING"
    VALIDATING = "VALIDATING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PUSHING = "PUSHING"
    COMPLETED = "COMPLETED"
    EXCEPTION = "EXCEPTION"
    PUSH_FAILED = "PUSH_FAILED"
    REJECTED = "REJECTED"


class ExceptionType(StrEnum):
    DUPLICATE = "DUPLICATE"
    UNKNOWN_VENDOR = "UNKNOWN_VENDOR"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    VAT_FLAG = "VAT_FLAG"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    AMBIGUOUS_CC = "AMBIGUOUS_CC"
    MATH_ERROR = "MATH_ERROR"


class Job(BaseModel):
    """Represents a single invoice processing job."""

    id: UUID = Field(default_factory=uuid4)
    gmail_message_id: str | None = None
    raw_drive_id: str | None = Field(None, description="Google Drive file ID in INBOX_RAW")
    raw_filename: str | None = None
    status: JobStatus = JobStatus.RECEIVED
    exception_type: ExceptionType | None = None
    exception_note: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def transition_to(self, new_status: JobStatus) -> None:
        """Transition the job to a new status with timestamp update."""
        self.status = new_status
        self.updated_at = datetime.utcnow()

    def mark_exception(self, exc_type: ExceptionType, note: str | None = None) -> None:
        """Mark the job as an exception."""
        self.status = JobStatus.EXCEPTION
        self.exception_type = exc_type
        self.exception_note = note
        self.updated_at = datetime.utcnow()


class AuditEntry(BaseModel):
    """A single audit log entry — immutable record of an action."""

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    action: str = Field(..., description="Action type: RECEIVED, EXTRACTED, VENDOR_MATCHED, etc.")
    actor: str = Field(
        default="system",
        description="'system' or Slack user ID",
    )
    details: dict | None = Field(
        None,
        description="Full context snapshot (before/after for corrections)",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
