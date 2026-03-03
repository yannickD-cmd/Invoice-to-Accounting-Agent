"""Database queries for approval workflow."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApprovalRequestRow


async def create_approval_request(session: AsyncSession, **kwargs) -> ApprovalRequestRow:
    request = ApprovalRequestRow(**kwargs)
    session.add(request)
    await session.commit()
    await session.refresh(request)
    return request


async def get_approval_for_job(session: AsyncSession, job_id: UUID) -> ApprovalRequestRow | None:
    result = await session.execute(
        select(ApprovalRequestRow).where(ApprovalRequestRow.job_id == job_id)
    )
    return result.scalar_one_or_none()


async def approve_request(
    session: AsyncSession,
    request_id: UUID,
    approved_by: str,
) -> None:
    await session.execute(
        update(ApprovalRequestRow)
        .where(ApprovalRequestRow.id == request_id)
        .values(status="APPROVED", approved_by=approved_by)
    )
    await session.commit()


async def reject_request(
    session: AsyncSession,
    request_id: UUID,
    rejected_by: str,
    reason: str | None = None,
) -> None:
    await session.execute(
        update(ApprovalRequestRow)
        .where(ApprovalRequestRow.id == request_id)
        .values(status="REJECTED", rejected_by=rejected_by, rejection_reason=reason)
    )
    await session.commit()


async def get_overdue_approvals(session: AsyncSession) -> list[ApprovalRequestRow]:
    """Return all pending approval requests past their deadline."""
    now = datetime.utcnow()
    result = await session.execute(
        select(ApprovalRequestRow).where(
            ApprovalRequestRow.status == "PENDING",
            ApprovalRequestRow.deadline < now,
        )
    )
    return list(result.scalars().all())


async def mark_escalated(session: AsyncSession, request_id: UUID) -> None:
    await session.execute(
        update(ApprovalRequestRow)
        .where(ApprovalRequestRow.id == request_id)
        .values(escalated=True, status="ESCALATED")
    )
    await session.commit()
