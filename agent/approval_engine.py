"""Approval rules engine — determines who must approve and deadlines."""

from __future__ import annotations

from decimal import Decimal

from agent.config import settings
from agent.constants import PROPERTIES_BY_CC
from agent.logging import get_logger
from agent.models.approval import ApprovalRequirement
from agent.models.invoice import InvoiceData
from agent.models.vendor import Vendor

logger = get_logger(__name__)


def get_approvers(
    invoice: InvoiceData,
    vendor: Vendor | None,
    cost_center: str | None = None,
) -> ApprovalRequirement:
    """Evaluate approval rules and return the required approvers + deadline.

    Rules (in priority order):
    5. Unrecognized vendor → Marie mandatory (24h)
    4. Maintenance >1000€ → Property Manager + Marie (48h)
    3. >2000€ OR insurance/legal → Marie + Direction (72h)
    2. 500€ – 2000€ → Marie (48h)
    1. <500€ → Thomas (24h)
    """
    total = invoice.total_ttc

    # Rule 5: Unknown vendor
    if vendor is None:
        logger.info("approval_rule", rule=5, reason="unknown_vendor")
        return ApprovalRequirement(
            approvers=[settings.slack_user_marie],
            deadline_hours=24,
            channel=settings.slack_channel_exceptions or "#invoice-exceptions",
        )

    gl = vendor.default_gl or ""

    # Rule 4: Maintenance >1000€ for a specific property
    if gl == "615000" and total > Decimal("1000") and cost_center:
        pm_id = settings.property_manager_slack_id(cost_center)
        approvers = [settings.slack_user_marie]
        if pm_id:
            approvers.insert(0, pm_id)
        logger.info("approval_rule", rule=4, reason="maintenance_over_1000", cost_center=cost_center)
        return ApprovalRequirement(
            approvers=approvers,
            deadline_hours=48,
            requires_all=True,
        )

    # Rule 3: >2000€ OR insurance/legal
    if total > Decimal("2000") or gl in ("616000", "622000"):
        logger.info("approval_rule", rule=3, reason="high_value_or_insurance", total=str(total), gl=gl)
        return ApprovalRequirement(
            approvers=[settings.slack_user_marie, settings.slack_user_direction],
            deadline_hours=72,
            requires_all=True,
        )

    # Rule 2: 500€ – 2000€
    if total >= Decimal("500"):
        logger.info("approval_rule", rule=2, reason="mid_value", total=str(total))
        return ApprovalRequirement(
            approvers=[settings.slack_user_marie],
            deadline_hours=48,
        )

    # Rule 1: <500€
    logger.info("approval_rule", rule=1, reason="low_value", total=str(total))
    return ApprovalRequirement(
        approvers=[settings.slack_user_thomas],
        deadline_hours=24,
    )
