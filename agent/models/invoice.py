"""Pydantic models for invoice extraction and processing."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────


class Currency(StrEnum):
    EUR = "EUR"
    USD = "USD"
    GBP = "GBP"


class Language(StrEnum):
    FR = "fr"
    EN = "en"


# ── Sub-models ─────────────────────────────────────────────────────────────


class VATLine(BaseModel):
    """A single VAT rate/amount breakdown line."""

    rate: Decimal = Field(..., description="VAT rate as decimal, e.g. 0.20 for 20%")
    base: Decimal = Field(..., description="HT amount subject to this rate")
    amount: Decimal = Field(..., description="VAT amount for this rate")


class LineItem(BaseModel):
    """A single invoice line item."""

    description: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    total: Decimal | None = None
    gl_hint: str | None = Field(
        None,
        description="Suggested GL account code based on line item nature",
    )


# ── Main extraction result ─────────────────────────────────────────────────


class InvoiceData(BaseModel):
    """Structured data extracted from an invoice PDF by Claude."""

    # Vendor identification
    vendor_name: str
    vendor_name_confidence: float = Field(..., ge=0, le=1)
    siret: str | None = None
    siret_confidence: float = Field(default=1.0, ge=0, le=1)

    # Invoice identifiers
    invoice_number: str
    invoice_number_confidence: float = Field(..., ge=0, le=1)
    invoice_date: date
    invoice_date_confidence: float = Field(..., ge=0, le=1)
    due_date: date | None = None
    due_date_confidence: float = Field(default=1.0, ge=0, le=1)

    # Amounts
    subtotal_ht: Decimal = Field(..., description="Total hors taxes")
    subtotal_ht_confidence: float = Field(..., ge=0, le=1)
    vat_lines: list[VATLine] = Field(default_factory=list, description="VAT breakdown by rate")
    total_ttc: Decimal = Field(..., description="Total toutes taxes comprises")
    total_ttc_confidence: float = Field(..., ge=0, le=1)

    # Line items
    line_items: list[LineItem] = Field(default_factory=list)

    # Metadata
    currency: Currency = Currency.EUR
    language: Language = Language.FR
    raw_confidence: float = Field(
        ...,
        ge=0,
        le=1,
        description="Overall extraction confidence",
    )

    @property
    def total_vat(self) -> Decimal:
        """Sum of all VAT line amounts."""
        return sum((v.amount for v in self.vat_lines), Decimal("0"))

    @property
    def critical_fields_confident(self) -> bool:
        """True if all critical fields have confidence >= 0.75."""
        return all(
            c >= 0.75
            for c in [
                self.vendor_name_confidence,
                self.invoice_number_confidence,
                self.invoice_date_confidence,
                self.subtotal_ht_confidence,
                self.total_ttc_confidence,
            ]
        )

    @property
    def low_confidence_fields(self) -> list[str]:
        """List field names where confidence is below 0.75."""
        checks = {
            "vendor_name": self.vendor_name_confidence,
            "invoice_number": self.invoice_number_confidence,
            "invoice_date": self.invoice_date_confidence,
            "subtotal_ht": self.subtotal_ht_confidence,
            "total_ttc": self.total_ttc_confidence,
            "siret": self.siret_confidence,
            "due_date": self.due_date_confidence,
        }
        return [name for name, conf in checks.items() if conf < 0.75]


# ── Enriched invoice (after vendor lookup + CC assignment) ─────────────────


class EnrichedInvoice(BaseModel):
    """InvoiceData plus resolved vendor/GL/cost-center information."""

    extracted: InvoiceData
    vendor_id: UUID | None = None
    vendor_code: str | None = None
    resolved_gl: str | None = None
    resolved_vat_rate: Decimal | None = None
    cost_center: str | None = None
    payment_terms_days: int | None = None
    is_multi_gl: bool = False
    gl_splits: list[dict] | None = Field(
        None,
        description="Per-line GL splits when line items span multiple accounts",
    )
