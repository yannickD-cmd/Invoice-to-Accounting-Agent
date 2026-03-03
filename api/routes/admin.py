"""Admin endpoints — manual triggers, job queries, retries."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agent.logging import get_logger
from db.connection import get_session
from db.queries.jobs import get_job, get_jobs_by_status, update_job_status

logger = get_logger(__name__)

router = APIRouter()


@router.get("/jobs")
async def list_jobs(
    status: str | None = None,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
):
    """List recent jobs, optionally filtered by status."""
    if status:
        jobs = await get_jobs_by_status(session, status)
    else:
        from sqlalchemy import select
        from db.models import JobRow

        result = await session.execute(
            select(JobRow).order_by(JobRow.created_at.desc()).limit(limit)
        )
        jobs = list(result.scalars().all())

    return [
        {
            "id": str(j.id),
            "status": j.status,
            "exception_type": j.exception_type,
            "raw_filename": j.raw_filename,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "updated_at": j.updated_at.isoformat() if j.updated_at else None,
        }
        for j in jobs[:limit]
    ]


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Retry a failed job by resetting its status."""
    job = await get_job(session, job_id)
    if not job:
        return {"error": "Job not found"}

    if job.status not in ("PUSH_FAILED", "EXCEPTION"):
        return {"error": f"Cannot retry job in status {job.status}"}

    await update_job_status(session, job_id, "RECEIVED")
    logger.info("job_retried", job_id=str(job_id))

    # TODO: trigger reprocessing pipeline
    return {"status": "retried", "job_id": str(job_id)}


@router.post("/sync-vendors")
async def sync_vendors():
    """Force a vendor sync to Notion."""
    logger.info("manual_vendor_sync_triggered")
    # TODO: Phase 4 — call notion_logger.sync_vendors()
    return {"status": "sync_triggered"}
