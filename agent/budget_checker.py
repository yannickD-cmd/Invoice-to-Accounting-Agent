"""Budget checker — compares invoice against remaining budget via Google Sheets."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from agent.clients.sheets_client import SheetsClient
from agent.logging import get_logger

logger = get_logger(__name__)

# Threshold: warn if invoice uses >90% of remaining budget
WARNING_THRESHOLD = Decimal("0.90")


@dataclass
class BudgetCheckResult:
    """Result of a budget check."""

    checked: bool = False         # False if budget data unavailable
    within_budget: bool = True
    remaining_budget: Decimal | None = None
    usage_ratio: Decimal | None = None  # invoice / remaining
    warning: str | None = None
    requires_direction: bool = False


async def check_budget(
    cost_center: str,
    gl_account: str,
    invoice_total: Decimal,
    invoice_month: int,
) -> BudgetCheckResult:
    """Check an invoice amount against remaining budget.

    Soft warning if invoice > 90% of remaining budget.
    Hard flag (requires Direction approval) if invoice > remaining budget.

    Returns BudgetCheckResult.
    """
    sheets = SheetsClient()
    remaining = await sheets.get_budget_remaining(cost_center, gl_account, invoice_month)

    if remaining is None:
        logger.info(
            "budget_check_skipped",
            reason="no_budget_data",
            cost_center=cost_center,
            gl_account=gl_account,
        )
        return BudgetCheckResult(checked=False)

    if remaining <= 0:
        logger.warning(
            "budget_exhausted",
            cost_center=cost_center,
            gl_account=gl_account,
            remaining=str(remaining),
        )
        return BudgetCheckResult(
            checked=True,
            within_budget=False,
            remaining_budget=remaining,
            usage_ratio=Decimal("999"),
            warning=f"Budget exhausted for {cost_center}/{gl_account}",
            requires_direction=True,
        )

    usage_ratio = invoice_total / remaining

    if usage_ratio > 1:
        logger.warning(
            "budget_exceeded",
            cost_center=cost_center,
            gl_account=gl_account,
            invoice=str(invoice_total),
            remaining=str(remaining),
            ratio=str(usage_ratio),
        )
        return BudgetCheckResult(
            checked=True,
            within_budget=False,
            remaining_budget=remaining,
            usage_ratio=usage_ratio,
            warning=f"Invoice €{invoice_total} exceeds remaining budget €{remaining}",
            requires_direction=True,
        )

    if usage_ratio > WARNING_THRESHOLD:
        logger.info(
            "budget_warning",
            cost_center=cost_center,
            gl_account=gl_account,
            invoice=str(invoice_total),
            remaining=str(remaining),
            ratio=str(usage_ratio),
        )
        return BudgetCheckResult(
            checked=True,
            within_budget=True,
            remaining_budget=remaining,
            usage_ratio=usage_ratio,
            warning=f"Invoice uses {usage_ratio * 100:.0f}% of remaining budget (€{remaining})",
        )

    return BudgetCheckResult(
        checked=True,
        within_budget=True,
        remaining_budget=remaining,
        usage_ratio=usage_ratio,
    )
