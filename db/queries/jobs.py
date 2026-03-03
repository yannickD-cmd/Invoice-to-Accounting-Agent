"""Database queries for job lifecycle operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLogRow, JobRow


async def create_job(session: AsyncSession, **kwargs) -> JobRow:
    job = JobRow(**kwargs)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def get_job(session: AsyncSession, job_id: UUID) -> JobRow | None:
    result = await session.execute(select(JobRow).where(JobRow.id == job_id))
    return result.scalar_one_or_none()


async def get_job_by_gmail_id(session: AsyncSession, gmail_message_id: str) -> JobRow | None:
    result = await session.execute(
        select(JobRow).where(JobRow.gmail_message_id == gmail_message_id)
    )
    return result.scalar_one_or_none()


async def update_job_status(
    session: AsyncSession,
    job_id: UUID,
    status: str,
    *,
    exception_type: str | None = None,
    exception_note: str | None = None,
    extracted_data: dict | None = None,
) -> None:
    values: dict = {"status": status}
    if exception_type is not None:
        values["exception_type"] = exception_type
    if exception_note is not None:
        values["exception_note"] = exception_note
    if extracted_data is not None:
        values["extracted_data"] = extracted_data
    await session.execute(update(JobRow).where(JobRow.id == job_id).values(**values))
    await session.commit()


async def write_audit_log(
    session: AsyncSession,
    job_id: UUID,
    action: str,
    actor: str = "system",
    details: dict | None = None,
) -> AuditLogRow:
    entry = AuditLogRow(job_id=job_id, action=action, actor=actor, details=details)
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def get_jobs_by_status(session: AsyncSession, status: str) -> list[JobRow]:
    result = await session.execute(
        select(JobRow).where(JobRow.status == status).order_by(JobRow.created_at.desc())
    )
    return list(result.scalars().all())
