"""Main pipeline — orchestrates the full invoice processing flow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from agent.approval_engine import get_approvers
from agent.budget_checker import check_budget
from agent.claude_agent import extract_invoice_with_claude
from agent.clients.drive_client import DriveClient
from agent.clients.gmail_client import IncomingEmail
from agent.clients.notion_client import NotionLogger
from agent.clients.slack_bot import (
    build_approval_message,
    build_exception_message,
    post_approval_request,
    post_to_channel,
)
from agent.config import settings
from agent.cost_center_router import resolve_cost_center
from agent.duplicate_detector import DuplicateResult, check_duplicate
from agent.extractor import extract_text_from_pdf
from agent.logging import get_logger
from agent.models.job import ExceptionType, JobStatus
from agent.vat_validator import validate_vat
from agent.vendor_memory import lookup_vendor
from db.connection import async_session
from db.queries.approvals import create_approval_request
from db.queries.jobs import create_job, update_job_status, write_audit_log

logger = get_logger(__name__)

drive = DriveClient()
notion = NotionLogger()


async def process_incoming_email(email: IncomingEmail) -> None:
    """Process a single incoming email with PDF attachment(s).

    This is the main orchestration function that drives the entire pipeline:
    Ingestion → Extraction → Enrichment → Validation → Approval → Output
    """
    async with async_session() as session:
        # ── 1. Dedup by Gmail Message-ID ───────────────────────────────
        from db.queries.jobs import get_job_by_gmail_id

        existing = await get_job_by_gmail_id(session, email.message_id)
        if existing:
            logger.info("email_already_processed", message_id=email.message_id)
            return

        # Process first PDF attachment only (Metro rule: first is invoice)
        if not email.attachments:
            logger.info("email_no_pdf", message_id=email.message_id)
            return

        attachment = email.attachments[0]

        if len(email.attachments) > 1:
            logger.info(
                "email_multiple_attachments",
                count=len(email.attachments),
                processing=attachment.filename,
            )

        # ── 2. Create job ──────────────────────────────────────────────
        job = await create_job(
            session,
            gmail_message_id=email.message_id,
            raw_filename=attachment.filename,
            status=JobStatus.RECEIVED,
        )
        job_id = job.id

        await write_audit_log(
            session, job_id, "RECEIVED",
            details={"sender": email.sender, "subject": email.subject},
        )

        logger.info(
            "job_created",
            job_id=str(job_id),
            sender=email.sender,
            filename=attachment.filename,
        )

        try:
            # ── 3. Upload to Drive INBOX_RAW ───────────────────────────
            drive_file_id = await drive.upload_to_inbox_raw(
                attachment.filename, attachment.data
            )
            await update_job_status(session, job_id, JobStatus.EXTRACTING)

            # ── 4. Extract text from PDF ───────────────────────────────
            extraction = await extract_text_from_pdf(attachment.data)

            if extraction.is_empty:
                await _handle_exception(
                    session, job_id, ExceptionType.LOW_CONFIDENCE,
                    "PDF text extraction returned empty",
                    drive_file_id, attachment.filename,
                )
                return

            # ── 5. Claude extraction ───────────────────────────────────
            invoice_data = await extract_invoice_with_claude(extraction.text)

            await update_job_status(
                session, job_id, JobStatus.ENRICHING,
                extracted_data=invoice_data.model_dump(mode="json"),
            )
            await write_audit_log(
                session, job_id, "EXTRACTED",
                details={
                    "vendor_name": invoice_data.vendor_name,
                    "total_ttc": str(invoice_data.total_ttc),
                    "confidence": invoice_data.raw_confidence,
                },
            )

            # ── 6. Confidence check ───────────────────────────────────
            if not invoice_data.critical_fields_confident:
                await _handle_exception(
                    session, job_id, ExceptionType.LOW_CONFIDENCE,
                    f"Low confidence on: {', '.join(invoice_data.low_confidence_fields)}",
                    drive_file_id, attachment.filename,
                    extra_details={
                        "vendor_name": invoice_data.vendor_name,
                        "invoice_number": invoice_data.invoice_number,
                        "total_ttc": str(invoice_data.total_ttc),
                        "low_fields": ", ".join(invoice_data.low_confidence_fields),
                    },
                )
                return

            # ── 7. Vendor memory lookup ────────────────────────────────
            vendor_match = await lookup_vendor(
                session,
                invoice_data.vendor_name,
                siret=invoice_data.siret,
            )

            if vendor_match.is_unknown:
                await _handle_exception(
                    session, job_id, ExceptionType.UNKNOWN_VENDOR,
                    f"Vendor not found: {invoice_data.vendor_name}",
                    drive_file_id, attachment.filename,
                    extra_details={
                        "vendor_name": invoice_data.vendor_name,
                        "siret": invoice_data.siret or "N/A",
                        "invoice_number": invoice_data.invoice_number,
                        "total_ttc": str(invoice_data.total_ttc),
                    },
                )
                return

            vendor = vendor_match.vendor
            await write_audit_log(
                session, job_id, "VENDOR_MATCHED",
                details={
                    "vendor_id": str(vendor.id),
                    "match_type": vendor_match.match_type,
                    "match_score": vendor_match.match_score,
                },
            )

            # ── 8. Cost center resolution ──────────────────────────────
            cost_center = resolve_cost_center(
                to_addrs=email.to,
                cc_addrs=email.cc,
                invoice_text=extraction.text,
                vendor=vendor,
            )

            if cost_center is None:
                await _handle_exception(
                    session, job_id, ExceptionType.AMBIGUOUS_CC,
                    "Could not determine cost center",
                    drive_file_id, attachment.filename,
                    extra_details={
                        "vendor_name": invoice_data.vendor_name,
                        "invoice_number": invoice_data.invoice_number,
                        "total_ttc": str(invoice_data.total_ttc),
                    },
                )
                return

            # ── 9. Duplicate detection ─────────────────────────────────
            dup_check = await check_duplicate(
                session,
                vendor_id=vendor.id,
                invoice_number=invoice_data.invoice_number,
                total_ttc=invoice_data.total_ttc,
                invoice_date=invoice_data.invoice_date,
                cost_center=cost_center,
            )

            if dup_check.result != DuplicateResult.UNIQUE:
                await _handle_exception(
                    session, job_id,
                    ExceptionType.DUPLICATE,
                    dup_check.match_reason,
                    drive_file_id, attachment.filename,
                    extra_details={
                        "vendor_name": invoice_data.vendor_name,
                        "invoice_number": invoice_data.invoice_number,
                        "total_ttc": str(invoice_data.total_ttc),
                        "match_reason": dup_check.match_reason,
                        "original_id": str(dup_check.original_invoice_id),
                    },
                )
                return

            # ── 10. VAT validation ─────────────────────────────────────
            gl_account = vendor.default_gl or ""
            vat_result = validate_vat(invoice_data, gl_account)

            if not vat_result.math_ok:
                await _handle_exception(
                    session, job_id, ExceptionType.MATH_ERROR,
                    "; ".join(vat_result.flags),
                    drive_file_id, attachment.filename,
                    extra_details={
                        "vendor_name": invoice_data.vendor_name,
                        "invoice_number": invoice_data.invoice_number,
                        "flags": vat_result.flags,
                    },
                )
                return

            await update_job_status(session, job_id, JobStatus.VALIDATING)

            # ── 11. Budget check ───────────────────────────────────────
            budget_result = await check_budget(
                cost_center=cost_center,
                gl_account=gl_account,
                invoice_total=invoice_data.total_ttc,
                invoice_month=invoice_data.invoice_date.month,
            )

            # ── 12. Build approval flags ───────────────────────────────
            approval_flags: list[str] = []

            if vat_result.has_warnings:
                approval_flags.extend(vat_result.flags)

            if budget_result.warning:
                approval_flags.append(budget_result.warning)

            if budget_result.requires_direction:
                approval_flags.append("⚠️ Direction approval required — budget exceeded")

            # ── 13. Determine approvers ────────────────────────────────
            approval_req = get_approvers(invoice_data, vendor, cost_center)

            # Add Direction if budget exceeded
            if budget_result.requires_direction:
                if settings.slack_user_direction not in approval_req.approvers:
                    approval_req.approvers.append(settings.slack_user_direction)

            # ── 14. Post approval request to Slack ─────────────────────
            invoice_summary = {
                "vendor_name": invoice_data.vendor_name,
                "invoice_number": invoice_data.invoice_number,
                "total_ttc": str(invoice_data.total_ttc),
                "cost_center": cost_center,
                "gl_account": gl_account,
                "invoice_date": str(invoice_data.invoice_date),
                "due_date": str(invoice_data.due_date) if invoice_data.due_date else "N/A",
            }

            blocks = build_approval_message(
                invoice_summary=invoice_summary,
                job_id=str(job_id),
                flags=approval_flags if approval_flags else None,
            )

            channel = approval_req.channel or settings.slack_channel_invoices
            message_ts = await post_approval_request(channel, blocks)

            # ── 15. Store approval request in DB ───────────────────────
            deadline = datetime.now(timezone.utc) + timedelta(hours=approval_req.deadline_hours)

            await create_approval_request(
                session,
                job_id=job_id,
                approvers=approval_req.approvers,
                deadline=deadline,
                slack_message_ts=message_ts,
            )

            await update_job_status(session, job_id, JobStatus.PENDING_APPROVAL)
            await write_audit_log(
                session, job_id, "APPROVAL_REQUESTED",
                details={
                    "approvers": approval_req.approvers,
                    "deadline_hours": approval_req.deadline_hours,
                    "flags": approval_flags,
                },
            )

            logger.info(
                "pipeline_approval_requested",
                job_id=str(job_id),
                vendor=invoice_data.vendor_name,
                total=str(invoice_data.total_ttc),
                approvers=approval_req.approvers,
                deadline_hours=approval_req.deadline_hours,
            )

        except Exception as exc:
            logger.error("pipeline_error", job_id=str(job_id), error=str(exc))
            await update_job_status(
                session, job_id, JobStatus.EXCEPTION,
                exception_note=f"Pipeline error: {exc}",
            )
            raise


async def _handle_exception(
    session,
    job_id,
    exc_type: ExceptionType,
    note: str,
    drive_file_id: str,
    filename: str,
    extra_details: dict | None = None,
) -> None:
    """Handle an exception: update DB, move file, notify Slack + Notion."""
    await update_job_status(
        session, job_id, JobStatus.EXCEPTION,
        exception_type=exc_type, exception_note=note,
    )
    await write_audit_log(
        session, job_id, f"EXCEPTION_{exc_type}",
        details={"note": note, **(extra_details or {})},
    )

    # Move to /EXCEPTIONS/ on Drive
    try:
        await drive.move_to_exceptions(drive_file_id, exc_type, filename)
    except Exception as exc:
        logger.error("drive_exception_move_failed", error=str(exc))

    # Notify Slack
    details_display = extra_details or {"note": note}
    blocks = build_exception_message(exc_type, details_display, str(job_id))
    await post_to_channel(
        settings.slack_channel_exceptions or "#invoice-exceptions",
        f"Exception: {exc_type}",
        blocks,
    )

    # Log to Notion
    await notion.create_pending_invoice(
        job_id=str(job_id),
        exception_type=exc_type,
        vendor_name=details_display.get("vendor_name", ""),
        invoice_number=details_display.get("invoice_number", ""),
        total_ttc=details_display.get("total_ttc", ""),
        owner="Marie",
    )

    logger.info("exception_handled", job_id=str(job_id), type=exc_type, note=note)
