"""Unit tests for cost center routing logic."""

from decimal import Decimal

import pytest

from agent.cost_center_router import resolve_cost_center
from agent.models.vendor import Vendor


class TestEmailHeaderResolution:
    """Test cost center detection from email To/CC headers."""

    def test_property_email_in_to(self):
        """Known property email in To header → resolved."""
        from agent.constants import PROPERTY_EMAIL_MAP

        # Temporarily add a test mapping
        PROPERTY_EMAIL_MAP["lecedre@test.com"] = "CC-01"
        try:
            result = resolve_cost_center(
                to_addrs=["lecedre@test.com"],
                cc_addrs=[],
                invoice_text="",
            )
            assert result == "CC-01"
        finally:
            del PROPERTY_EMAIL_MAP["lecedre@test.com"]

    def test_property_email_in_cc(self):
        """Known property email in CC header → resolved."""
        from agent.constants import PROPERTY_EMAIL_MAP

        PROPERTY_EMAIL_MAP["desarenes@test.com"] = "CC-02"
        try:
            result = resolve_cost_center(
                to_addrs=["ap@company.com"],
                cc_addrs=["desarenes@test.com"],
                invoice_text="",
            )
            assert result == "CC-02"
        finally:
            del PROPERTY_EMAIL_MAP["desarenes@test.com"]

    def test_unknown_email_no_match(self):
        """Unknown email addresses, no PDF content → None."""
        result = resolve_cost_center(
            to_addrs=["unknown@company.com"],
            cc_addrs=[],
            invoice_text="",
        )
        assert result is None


class TestVendorDefault:
    """Test vendor-based cost center resolution."""

    def test_single_cc_vendor(self):
        """Vendor with one cost center → resolved."""
        vendor = Vendor(vendor_name="Test", cost_centers=["CC-03"])
        result = resolve_cost_center(
            to_addrs=[],
            cc_addrs=[],
            invoice_text="some unrelated text",
            vendor=vendor,
        )
        assert result == "CC-03"

    def test_multi_cc_vendor_ambiguous(self):
        """Vendor with multiple cost centers → None (ambiguous)."""
        vendor = Vendor(vendor_name="Test", cost_centers=["CC-01", "CC-03"])
        result = resolve_cost_center(
            to_addrs=[],
            cc_addrs=[],
            invoice_text="no property mentioned here",
            vendor=vendor,
        )
        assert result is None


class TestPDFContentResolution:
    """Test cost center detection from invoice PDF text."""

    def test_property_name_in_text(self):
        """Property name mentioned in invoice text → resolved."""
        result = resolve_cost_center(
            to_addrs=[],
            cc_addrs=[],
            invoice_text="Facture adressée à Villa Margot, 12 rue de la Paix",
        )
        assert result == "CC-03"

    def test_no_property_in_text(self):
        """No property mentioned → None."""
        result = resolve_cost_center(
            to_addrs=[],
            cc_addrs=[],
            invoice_text="Facture générique sans adresse",
        )
        assert result is None
