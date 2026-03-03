"""Shared pytest fixtures."""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from agent.models.invoice import InvoiceData, VATLine
from agent.models.vendor import Vendor


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_db_session():
    """Async mock for DB session dependency injection."""
    return AsyncMock()


@pytest.fixture
def sample_invoice() -> InvoiceData:
    """A valid French invoice (Metro) for testing."""
    return InvoiceData(
        vendor_name="Metro Cash & Carry",
        vendor_name_confidence=0.98,
        siret="12345678901234",
        siret_confidence=0.95,
        invoice_number="FR-2025-001234",
        invoice_number_confidence=0.99,
        invoice_date="2025-06-01",
        invoice_date_confidence=0.97,
        due_date="2025-06-30",
        due_date_confidence=0.90,
        subtotal_ht=Decimal("1000.00"),
        subtotal_ht_confidence=0.96,
        vat_lines=[
            VATLine(rate=Decimal("0.055"), base=Decimal("400.00"), amount=Decimal("22.00")),
            VATLine(rate=Decimal("0.20"), base=Decimal("600.00"), amount=Decimal("120.00")),
        ],
        total_ttc=Decimal("1142.00"),
        total_ttc_confidence=0.97,
        raw_confidence=0.96,
        currency="EUR",
        payment_method="virement",
        iban="FR7612345678901234567890123",
    )


@pytest.fixture
def sample_vendor() -> Vendor:
    """A known vendor record for Metro."""
    return Vendor(
        id="11111111-1111-1111-1111-111111111111",
        vendor_name="Metro Cash & Carry",
        siret="12345678901234",
        aliases=["METRO", "Metro C&C"],
        default_gl="607100",
        default_vat=Decimal("0.20"),
        cost_centers=["CC-01", "CC-03", "CC-04"],
        payment_terms_days=30,
    )


@pytest.fixture
def insurance_vendor() -> Vendor:
    """An insurance vendor (GL 616000)."""
    return Vendor(
        id="22222222-2222-2222-2222-222222222222",
        vendor_name="AXA Assurances",
        default_gl="616000",
        default_vat=Decimal("0.00"),
        cost_centers=["CC-01", "CC-02", "CC-03", "CC-04", "CC-05", "CC-06", "CC-07", "CC-08"],
    )


@pytest.fixture
def maintenance_vendor() -> Vendor:
    """A maintenance vendor (GL 615000)."""
    return Vendor(
        id="33333333-3333-3333-3333-333333333333",
        vendor_name="Plomberie Express",
        default_gl="615000",
        default_vat=Decimal("0.20"),
        cost_centers=["CC-01"],
        payment_terms_days=30,
    )
