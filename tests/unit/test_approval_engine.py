"""Unit tests for the approval rules engine."""

from decimal import Decimal
from unittest.mock import patch

import pytest

from agent.approval_engine import get_approvers
from agent.models.invoice import InvoiceData, VATLine
from agent.models.vendor import Vendor


def _make_invoice(total: Decimal, **kwargs) -> InvoiceData:
    """Helper to create a minimal InvoiceData for testing."""
    defaults = dict(
        vendor_name="Test Vendor",
        vendor_name_confidence=1.0,
        invoice_number="F-001",
        invoice_number_confidence=1.0,
        invoice_date="2025-06-01",
        invoice_date_confidence=1.0,
        subtotal_ht=total / Decimal("1.20"),
        subtotal_ht_confidence=1.0,
        vat_lines=[VATLine(rate=Decimal("0.20"), base=total / Decimal("1.20"), amount=total - total / Decimal("1.20"))],
        total_ttc=total,
        total_ttc_confidence=1.0,
        raw_confidence=0.95,
    )
    defaults.update(kwargs)
    return InvoiceData(**defaults)


def _make_vendor(gl: str = "615000", **kwargs) -> Vendor:
    """Helper to create a minimal Vendor for testing."""
    defaults = dict(
        vendor_name="Test Vendor",
        default_gl=gl,
        default_vat=Decimal("0.20"),
        cost_centers=["CC-01"],
    )
    defaults.update(kwargs)
    return Vendor(**defaults)


class TestApprovalRules:
    """Test all 5 approval routing rules + boundary values."""

    @patch("agent.approval_engine.settings")
    def test_rule1_under_500(self, mock_settings):
        """<500€ → Thomas, 24h deadline."""
        mock_settings.slack_user_thomas = "U_THOMAS"
        mock_settings.slack_user_marie = "U_MARIE"

        invoice = _make_invoice(Decimal("499.99"))
        vendor = _make_vendor()

        result = get_approvers(invoice, vendor)

        assert result.approvers == ["U_THOMAS"]
        assert result.deadline_hours == 24

    @patch("agent.approval_engine.settings")
    def test_rule2_500_to_2000(self, mock_settings):
        """500€ – 2000€ → Marie, 48h deadline."""
        mock_settings.slack_user_marie = "U_MARIE"
        mock_settings.slack_user_thomas = "U_THOMAS"

        invoice = _make_invoice(Decimal("500.00"))
        vendor = _make_vendor(gl="606200")

        result = get_approvers(invoice, vendor)

        assert result.approvers == ["U_MARIE"]
        assert result.deadline_hours == 48

    @patch("agent.approval_engine.settings")
    def test_rule2_upper_boundary(self, mock_settings):
        """2000€ exactly → Marie, 48h (rule 2, not rule 3)."""
        mock_settings.slack_user_marie = "U_MARIE"
        mock_settings.slack_user_thomas = "U_THOMAS"

        invoice = _make_invoice(Decimal("2000.00"))
        vendor = _make_vendor(gl="606200")

        result = get_approvers(invoice, vendor)

        assert result.approvers == ["U_MARIE"]
        assert result.deadline_hours == 48

    @patch("agent.approval_engine.settings")
    def test_rule3_over_2000(self, mock_settings):
        """>2000€ → Marie + Direction, 72h."""
        mock_settings.slack_user_marie = "U_MARIE"
        mock_settings.slack_user_direction = "U_DIRECTION"

        invoice = _make_invoice(Decimal("2000.01"))
        vendor = _make_vendor(gl="606200")

        result = get_approvers(invoice, vendor)

        assert set(result.approvers) == {"U_MARIE", "U_DIRECTION"}
        assert result.deadline_hours == 72

    @patch("agent.approval_engine.settings")
    def test_rule3_insurance(self, mock_settings):
        """Insurance vendor (GL 616000) any amount → Marie + Direction, 72h."""
        mock_settings.slack_user_marie = "U_MARIE"
        mock_settings.slack_user_direction = "U_DIRECTION"

        invoice = _make_invoice(Decimal("100.00"))
        vendor = _make_vendor(gl="616000")

        result = get_approvers(invoice, vendor)

        assert set(result.approvers) == {"U_MARIE", "U_DIRECTION"}
        assert result.deadline_hours == 72

    @patch("agent.approval_engine.settings")
    def test_rule4_maintenance_over_1000(self, mock_settings):
        """Maintenance >1000€ → Property Manager + Marie, 48h."""
        mock_settings.slack_user_marie = "U_MARIE"
        mock_settings.property_manager_slack_id = lambda cc: "U_PM_CC01" if cc == "CC-01" else None

        invoice = _make_invoice(Decimal("1500.00"))
        vendor = _make_vendor(gl="615000")

        result = get_approvers(invoice, vendor, cost_center="CC-01")

        assert "U_MARIE" in result.approvers
        assert "U_PM_CC01" in result.approvers
        assert result.deadline_hours == 48

    @patch("agent.approval_engine.settings")
    def test_rule5_unknown_vendor(self, mock_settings):
        """Unknown vendor → Marie mandatory, 24h, exceptions channel."""
        mock_settings.slack_user_marie = "U_MARIE"
        mock_settings.slack_channel_exceptions = "#invoice-exceptions"

        invoice = _make_invoice(Decimal("100.00"))

        result = get_approvers(invoice, vendor=None)

        assert result.approvers == ["U_MARIE"]
        assert result.deadline_hours == 24
        assert "exception" in result.channel.lower()
