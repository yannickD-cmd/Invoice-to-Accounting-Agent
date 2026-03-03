"""Duplicate invoice detector."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.logging import get_logger
from db.models import ProcessedInvoiceRow

logger = get_logger(__name__)


class DuplicateResult(StrEnum):
    UNIQUE = "UNIQUE"
    PROBABLE_DUPLICATE = "PROBABLE_DUPLICATE"
    CONFIRMED_DUPLICATE = "CONFIRMED_DUPLICATE"


class DuplicateCheckOutput:
    def __init__(
        self,
        result: DuplicateResult,
        original_invoice_id: UUID | None = None,
        match_reason: str = "",
    ):
        self.result = result
        self.original_invoice_id = original_invoice_id
        self.match_reason = match_reason


async def check_duplicate(
    session: AsyncSession,
    vendor_id: UUID | None,
    invoice_number: str,
    total_ttc: Decimal,
    invoice_date: date,
    cost_center: str | None = None,
) -> DuplicateCheckOutput:
    """Check if an invoice is a duplicate.

    Primary check: vendor_id + invoice_number + total_ttc → CONFIRMED
    Secondary check: vendor_id + invoice_date + total_ttc → PROBABLE
      (catches Metro/Transgourmet invoice number reuse across properties)

    The secondary check includes cost_center to avoid false positives.
    """
    if vendor_id is None:
        return DuplicateCheckOutput(result=DuplicateResult.UNIQUE)

    # ── Primary: exact match on vendor + invoice number + amount ───────
    primary = await session.execute(
        select(ProcessedInvoiceRow).where(
            and_(
                ProcessedInvoiceRow.vendor_id == vendor_id,
                ProcessedInvoiceRow.invoice_number == invoice_number,
                ProcessedInvoiceRow.total_ttc == total_ttc,
                ProcessedInvoiceRow.status != "REJECTED",
            )
        )
    )
    primary_match = primary.scalar_one_or_none()

    if primary_match:
        logger.warning(
            "duplicate_confirmed",
            vendor_id=str(vendor_id),
            invoice_number=invoice_number,
            total_ttc=str(total_ttc),
            original_id=str(primary_match.id),
        )
        return DuplicateCheckOutput(
            result=DuplicateResult.CONFIRMED_DUPLICATE,
            original_invoice_id=primary_match.id,
            match_reason=f"Exact match: vendor + invoice #{invoice_number} + €{total_ttc}",
        )

    # ── Secondary: same vendor + date + amount (different invoice #) ───
    secondary = await session.execute(
        select(ProcessedInvoiceRow).where(
            and_(
                ProcessedInvoiceRow.vendor_id == vendor_id,
                ProcessedInvoiceRow.invoice_date == invoice_date,
                ProcessedInvoiceRow.total_ttc == total_ttc,
                ProcessedInvoiceRow.status != "REJECTED",
                # For Metro/Transgourmet: also match cost center
                or_(
                    ProcessedInvoiceRow.cost_center == cost_center,
                    cost_center is None,
                ),
            )
        )
    )
    secondary_match = secondary.scalar_one_or_none()

    if secondary_match:
        logger.warning(
            "duplicate_probable",
            vendor_id=str(vendor_id),
            invoice_date=str(invoice_date),
            total_ttc=str(total_ttc),
            original_id=str(secondary_match.id),
        )
        return DuplicateCheckOutput(
            result=DuplicateResult.PROBABLE_DUPLICATE,
            original_invoice_id=secondary_match.id,
            match_reason=(
                f"Probable match: vendor + date {invoice_date} + €{total_ttc} "
                f"(original invoice #{secondary_match.invoice_number})"
            ),
        )

    return DuplicateCheckOutput(result=DuplicateResult.UNIQUE)
