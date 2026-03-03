"""Pydantic models for the approval workflow."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"


class ApprovalRequirement(BaseModel):
    """Output of the approval rules engine — who must approve and by when."""

    approvers: list[str] = Field(..., description="Slack user IDs of required approvers")
    deadline_hours: int = Field(..., description="Hours allowed before escalation")
    channel: str = Field(
        default="#invoices-to-approve",
        description="Slack channel to post the approval request",
    )
    requires_all: bool = Field(
        default=False,
        description="True if ALL approvers must approve (multi-approver flow)",
    )


class ApprovalRequest(BaseModel):
    """A tracked approval request stored in the database."""

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    approvers: list[str] = Field(..., description="Slack user IDs")
    deadline: datetime
    escalated: bool = False
    status: ApprovalStatus = ApprovalStatus.PENDING
    approved_by: str | None = None
    rejected_by: str | None = None
    rejection_reason: str | None = None
    slack_message_ts: str | None = Field(
        None,
        description="Slack message timestamp for updating the original message",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def is_resolved(self) -> bool:
        return self.status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED)
