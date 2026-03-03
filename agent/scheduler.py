"""APScheduler setup — persistent scheduled jobs for monitoring and maintenance."""

from __future__ import annotations

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agent.config import settings
from agent.logging import get_logger

logger = get_logger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the APScheduler instance.

    Uses PostgreSQL job store for persistence across Render restarts.
    """
    # Use the sync version of the DB URL for APScheduler
    sync_db_url = settings.database_url.replace("+asyncpg", "")

    jobstores = {
        "default": SQLAlchemyJobStore(url=sync_db_url),
    }

    scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        job_defaults={
            "coalesce": True,       # If multiple runs were missed, run once
            "max_instances": 1,     # Never run the same job concurrently
            "misfire_grace_time": 300,  # 5 min grace for cold starts
        },
    )

    return scheduler


async def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register all scheduled jobs."""

    # Check for overdue approvals — every 30 minutes
    scheduler.add_job(
        check_overdue_approvals,
        "interval",
        minutes=30,
        id="check_overdue_approvals",
        replace_existing=True,
    )

    # Check for late payments — daily at 08:00
    scheduler.add_job(
        check_late_payments,
        "cron",
        hour=8,
        minute=0,
        id="check_late_payments",
        replace_existing=True,
    )

    # Sync vendors to Notion — nightly at 02:00
    scheduler.add_job(
        sync_vendors_to_notion,
        "cron",
        hour=2,
        minute=0,
        id="sync_vendor_notion",
        replace_existing=True,
    )

    # Weekly budget report — Monday at 07:00
    scheduler.add_job(
        send_budget_report,
        "cron",
        day_of_week="mon",
        hour=7,
        minute=0,
        id="budget_report",
        replace_existing=True,
    )

    # Daily digest — every day at 08:30
    scheduler.add_job(
        send_daily_digest,
        "cron",
        hour=8,
        minute=30,
        id="daily_digest",
        replace_existing=True,
    )

    logger.info("scheduler_jobs_registered", count=5)


# ── Job Functions ──────────────────────────────────────────────────────────


async def check_overdue_approvals() -> None:
    """Find pending approvals past their deadline and escalate."""
    logger.info("scheduler_running", job="check_overdue_approvals")

    from db.connection import async_session
    from db.queries.approvals import get_overdue_approvals, mark_escalated

    async with async_session() as session:
        overdue = await get_overdue_approvals(session)

        if not overdue:
            return

        logger.warning("overdue_approvals_found", count=len(overdue))

        for req in overdue:
            if not req.escalated:
                await mark_escalated(session, req.id)
                # TODO: post to #finance-alerts + email Marie
                logger.warning(
                    "approval_escalated",
                    job_id=str(req.job_id),
                    deadline=str(req.deadline),
                )


async def check_late_payments() -> None:
    """Check for invoices approaching or past due date."""
    logger.info("scheduler_running", job="check_late_payments")
    # TODO: Phase 5 — implement late_payment_tracker.check_late_payments()


async def sync_vendors_to_notion() -> None:
    """Sync vendor records from PostgreSQL to Notion Fournisseurs database."""
    logger.info("scheduler_running", job="sync_vendor_notion")

    from agent.clients.notion_client import NotionLogger
    from db.connection import async_session
    from db.queries.vendors import get_all_active_vendors

    notion = NotionLogger()

    async with async_session() as session:
        vendors = await get_all_active_vendors(session)

        for v in vendors:
            await notion.sync_vendor(
                vendor_id=str(v.id),
                vendor_name=v.vendor_name,
                siret=v.siret or "",
                default_gl=v.default_gl or "",
                default_vat=str(v.default_vat or ""),
                cost_centers=", ".join(v.cost_centers or []),
                payment_terms=str(v.payment_terms or ""),
                notes=v.notes or "",
            )

        logger.info("vendor_notion_sync_complete", count=len(vendors))


async def send_budget_report() -> None:
    """Post a weekly budget summary to #finance-ops."""
    logger.info("scheduler_running", job="budget_report")
    # TODO: Phase 5 — aggregate budget data by cost center and post to Slack


async def send_daily_digest() -> None:
    """Post a daily processing summary to #finance-ops."""
    logger.info("scheduler_running", job="daily_digest")
    # TODO: Phase 5 — query jobs from last 24h and build digest message
