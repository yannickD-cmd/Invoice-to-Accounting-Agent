"""Cost center router — determines which property an invoice belongs to."""

from __future__ import annotations

from rapidfuzz import fuzz

from agent.constants import PROPERTIES, PROPERTY_EMAIL_MAP, Property
from agent.logging import get_logger
from agent.models.vendor import Vendor

logger = get_logger(__name__)

# Minimum fuzzy score to consider a property match from PDF content
PDF_FUZZY_THRESHOLD = 75


def resolve_cost_center(
    to_addrs: list[str],
    cc_addrs: list[str],
    invoice_text: str,
    vendor: Vendor | None = None,
) -> str | None:
    """Determine cost center using a priority chain:

    1. Email To/CC headers → property email map
    2. Invoice PDF content → fuzzy match against property names/addresses
    3. Vendor default cost center (if vendor always invoices one property)
    4. None → ambiguous, needs human selection

    Returns cost center code ("CC-01") or None.
    """
    # ── 1. Email header detection ──────────────────────────────────────
    all_addrs = to_addrs + cc_addrs
    for addr in all_addrs:
        addr_lower = addr.lower().strip()
        if addr_lower in PROPERTY_EMAIL_MAP:
            cc = PROPERTY_EMAIL_MAP[addr_lower]
            logger.info("cost_center_resolved", method="email_header", cost_center=cc, email=addr_lower)
            return cc

    # ── 2. PDF content fuzzy match ─────────────────────────────────────
    if invoice_text:
        text_lower = invoice_text.lower()
        best_match: tuple[str, int] | None = None

        for prop in PROPERTIES:
            # Match against property name
            score = fuzz.partial_ratio(prop.name.lower(), text_lower)
            if score >= PDF_FUZZY_THRESHOLD:
                if best_match is None or score > best_match[1]:
                    best_match = (prop.cost_center, score)

        if best_match:
            logger.info(
                "cost_center_resolved",
                method="pdf_content",
                cost_center=best_match[0],
                score=best_match[1],
            )
            return best_match[0]

    # ── 3. Vendor default cost center ──────────────────────────────────
    if vendor and vendor.cost_centers:
        if len(vendor.cost_centers) == 1:
            cc = vendor.cost_centers[0]
            logger.info("cost_center_resolved", method="vendor_default", cost_center=cc)
            return cc
        else:
            logger.info(
                "cost_center_ambiguous",
                method="vendor_multi_cc",
                options=vendor.cost_centers,
            )
            # Multiple possible CCs for this vendor — can't auto-resolve
            return None

    # ── 4. No match ────────────────────────────────────────────────────
    logger.info("cost_center_unresolved")
    return None
