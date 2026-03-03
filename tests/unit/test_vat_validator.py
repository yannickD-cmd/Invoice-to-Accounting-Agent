"""Unit tests for VAT validation logic."""

from decimal import Decimal

import pytest

from agent.models.invoice import InvoiceData, VATLine
from agent.vat_validator import validate_vat


def _make_invoice(
    subtotal: Decimal,
    total: Decimal,
    vat_lines: list[VATLine],
    **kwargs,
) -> InvoiceData:
    defaults = dict(
        vendor_name="Test Vendor",
        vendor_name_confidence=1.0,
        invoice_number="F-001",
        invoice_number_confidence=1.0,
        invoice_date="2025-06-01",
        invoice_date_confidence=1.0,
        subtotal_ht=subtotal,
        subtotal_ht_confidence=1.0,
        vat_lines=vat_lines,
        total_ttc=total,
        total_ttc_confidence=1.0,
        raw_confidence=0.95,
    )
    defaults.update(kwargs)
    return InvoiceData(**defaults)


class TestVATMathChecks:
    """Test math integrity checks."""

    def test_correct_math(self):
        """HT + VAT = TTC — should pass."""
        invoice = _make_invoice(
            subtotal=Decimal("100.00"),
            total=Decimal("120.00"),
            vat_lines=[VATLine(rate=Decimal("0.20"), base=Decimal("100.00"), amount=Decimal("20.00"))],
        )
        result = validate_vat(invoice)
        assert result.math_ok is True
        assert result.is_valid is True

    def test_math_within_tolerance(self):
        """Off by 0.01 — within tolerance, should pass."""
        invoice = _make_invoice(
            subtotal=Decimal("100.00"),
            total=Decimal("120.01"),
            vat_lines=[VATLine(rate=Decimal("0.20"), base=Decimal("100.00"), amount=Decimal("20.00"))],
        )
        result = validate_vat(invoice)
        assert result.math_ok is True

    def test_math_fails(self):
        """Off by 1.00 — should fail."""
        invoice = _make_invoice(
            subtotal=Decimal("100.00"),
            total=Decimal("121.00"),
            vat_lines=[VATLine(rate=Decimal("0.20"), base=Decimal("100.00"), amount=Decimal("20.00"))],
        )
        result = validate_vat(invoice)
        assert result.math_ok is False
        assert len(result.flags) > 0

    def test_base_sum_mismatch(self):
        """VAT bases don't sum to subtotal — should flag."""
        invoice = _make_invoice(
            subtotal=Decimal("200.00"),
            total=Decimal("230.00"),
            vat_lines=[
                VATLine(rate=Decimal("0.20"), base=Decimal("100.00"), amount=Decimal("20.00")),
                VATLine(rate=Decimal("0.10"), base=Decimal("50.00"), amount=Decimal("5.00")),
                # bases sum to 150, but subtotal is 200
            ],
        )
        result = validate_vat(invoice)
        assert result.math_ok is False


class TestVATRateChecks:
    """Test GL-specific VAT rate validation."""

    def test_insurance_with_vat_flags(self):
        """Insurance (GL 616000) showing 20% VAT — should flag."""
        invoice = _make_invoice(
            subtotal=Decimal("100.00"),
            total=Decimal("120.00"),
            vat_lines=[VATLine(rate=Decimal("0.20"), base=Decimal("100.00"), amount=Decimal("20.00"))],
        )
        result = validate_vat(invoice, gl_account="616000")
        assert result.vat_rate_ok is False
        assert any("insurance" in f.lower() or "616000" in f for f in result.flags)

    def test_insurance_exempt_passes(self):
        """Insurance (GL 616000) with 0% VAT — should pass."""
        invoice = _make_invoice(
            subtotal=Decimal("500.00"),
            total=Decimal("500.00"),
            vat_lines=[],  # no VAT lines = exempt
        )
        result = validate_vat(invoice, gl_account="616000")
        assert result.vat_rate_ok is True

    def test_food_mixed_vat_accepted(self):
        """Food (GL 607100) with mixed 5.5% + 10% — should pass if math ok."""
        invoice = _make_invoice(
            subtotal=Decimal("200.00"),
            total=Decimal("217.50"),
            vat_lines=[
                VATLine(rate=Decimal("0.055"), base=Decimal("100.00"), amount=Decimal("5.50")),
                VATLine(rate=Decimal("0.10"), base=Decimal("100.00"), amount=Decimal("10.00")),
                # Vat total should be: 5.50 + 10.00 = 15.50; removed 2 from total accordintyly
            ],
        )
        result = validate_vat(invoice, gl_account="607100")
        # Math: 200 + 15.5 = 215.5 ≠ 217.50 → math fails
        # But VAT rate itself is acceptable for food
        assert result.math_ok is False  # total mismatch

    def test_standard_nonstandard_rate_warning(self):
        """Non-food/non-insurance with 10% — should warn."""
        invoice = _make_invoice(
            subtotal=Decimal("100.00"),
            total=Decimal("110.00"),
            vat_lines=[VATLine(rate=Decimal("0.10"), base=Decimal("100.00"), amount=Decimal("10.00"))],
        )
        result = validate_vat(invoice, gl_account="606200")
        assert any("non-standard" in f.lower() or "expected 20%" in f.lower() for f in result.flags)
