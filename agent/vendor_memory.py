"""Vendor memory — DB lookup with SIRET, fuzzy name, and alias matching."""

from __future__ import annotations

from rapidfuzz import fuzz, process
from sqlalchemy.ext.asyncio import AsyncSession

from agent.logging import get_logger
from agent.models.vendor import Vendor, VendorMatch
from db.queries.vendors import get_all_active_vendors, get_vendor_by_siret

logger = get_logger(__name__)

# Minimum score for a fuzzy match to be considered valid (0-100 scale from rapidfuzz)
FUZZY_THRESHOLD = 80


async def lookup_vendor(
    session: AsyncSession,
    vendor_name: str,
    siret: str | None = None,
) -> VendorMatch:
    """Look up a vendor using a priority chain:
    1. SIRET exact match
    2. Exact vendor name match (case-insensitive)
    3. Fuzzy alias match (rapidfuzz)

    Returns VendorMatch with match details, or empty match if not found.
    """
    # ── 1. SIRET match (highest priority) ──────────────────────────────
    if siret:
        row = await get_vendor_by_siret(session, siret)
        if row:
            logger.info("vendor_matched", method="siret", vendor=row.vendor_name, siret=siret)
            return VendorMatch(
                vendor=_row_to_vendor(row),
                match_type="siret",
                match_score=1.0,
            )

    # ── 2. Exact name + alias scan ─────────────────────────────────────
    all_vendors = await get_all_active_vendors(session)
    name_lower = vendor_name.lower().strip()

    for row in all_vendors:
        # Exact name match
        if row.vendor_name.lower().strip() == name_lower:
            logger.info("vendor_matched", method="exact_name", vendor=row.vendor_name)
            return VendorMatch(
                vendor=_row_to_vendor(row),
                match_type="exact_name",
                match_score=1.0,
            )

        # Exact alias match
        for alias in (row.aliases or []):
            if alias.lower().strip() == name_lower:
                logger.info(
                    "vendor_matched",
                    method="exact_alias",
                    vendor=row.vendor_name,
                    alias=alias,
                )
                return VendorMatch(
                    vendor=_row_to_vendor(row),
                    match_type="exact_alias",
                    match_score=1.0,
                )

    # ── 3. Fuzzy match ─────────────────────────────────────────────────
    candidates: list[tuple[str, object]] = []
    for row in all_vendors:
        candidates.append((row.vendor_name, row))
        for alias in (row.aliases or []):
            candidates.append((alias, row))

    if candidates:
        names = [c[0] for c in candidates]
        result = process.extractOne(
            vendor_name,
            names,
            scorer=fuzz.token_sort_ratio,
        )

        if result and result[1] >= FUZZY_THRESHOLD:
            matched_name, score, idx = result
            matched_row = candidates[idx][1]
            logger.info(
                "vendor_matched",
                method="fuzzy",
                vendor=matched_row.vendor_name,
                query=vendor_name,
                score=score,
            )
            return VendorMatch(
                vendor=_row_to_vendor(matched_row),
                match_type="fuzzy_alias",
                match_score=score / 100.0,
            )

    # ── Miss ───────────────────────────────────────────────────────────
    logger.info("vendor_not_found", query=vendor_name, siret=siret)
    return VendorMatch()


def _row_to_vendor(row) -> Vendor:
    """Convert a SQLAlchemy VendorRow to a Pydantic Vendor model."""
    return Vendor(
        id=row.id,
        vendor_name=row.vendor_name,
        aliases=row.aliases or [],
        siret=row.siret,
        default_gl=row.default_gl,
        default_vat=row.default_vat,
        cost_centers=row.cost_centers or [],
        payment_terms=int(row.payment_terms) if row.payment_terms else None,
        notes=row.notes,
        is_active=row.is_active,
        last_corrected_by=row.last_corrected_by,
        last_corrected_at=row.last_corrected_at,
        created_at=row.created_at,
    )
