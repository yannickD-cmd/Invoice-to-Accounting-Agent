"""Pydantic models for vendor / supplier data."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Vendor(BaseModel):
    """Represents a known supplier in the vendor memory."""

    id: UUID = Field(default_factory=uuid4)
    vendor_name: str
    aliases: list[str] = Field(default_factory=list, description="Known name variants")
    siret: str | None = None
    default_gl: str | None = Field(None, description="Default GL account code, e.g. '615000'")
    default_vat: Decimal | None = Field(None, description="Default VAT rate as decimal, e.g. 0.20")
    cost_centers: list[str] = Field(
        default_factory=list,
        description="Usual cost center codes, e.g. ['CC-01', 'CC-03']",
    )
    payment_terms: int | None = Field(None, description="Payment terms in days (30, 45, 0)")
    notes: str | None = None
    is_active: bool = True
    last_corrected_by: str | None = Field(None, description="Slack user ID of last corrector")
    last_corrected_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class VendorMatch(BaseModel):
    """Result of a vendor memory lookup."""

    vendor: Vendor | None = None
    match_type: str | None = Field(
        None,
        description="How the match was made: 'siret' | 'exact_name' | 'fuzzy_alias' | None",
    )
    match_score: float | None = Field(
        None,
        ge=0,
        le=1,
        description="Fuzzy match score (1.0 = exact)",
    )

    @property
    def is_match(self) -> bool:
        return self.vendor is not None

    @property
    def is_unknown(self) -> bool:
        return self.vendor is None
