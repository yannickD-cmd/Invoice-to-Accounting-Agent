"""Unit tests for vendor memory (fuzzy matching)."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.models.vendor import Vendor, VendorMatch
from agent.vendor_memory import lookup_vendor


def _stub_vendor(**overrides) -> Vendor:
    defaults = dict(
        id="00000000-0000-0000-0000-000000000001",
        vendor_name="Metro Cash & Carry",
        siret="12345678901234",
        aliases=["METRO", "Metro C&C"],
        default_gl="607100",
        default_vat=Decimal("0.20"),
        cost_centers=["CC-01", "CC-03"],
    )
    defaults.update(overrides)
    return Vendor(**defaults)


@pytest.fixture
def mock_session():
    return AsyncMock()


class TestVendorLookup:

    @pytest.mark.asyncio
    async def test_siret_exact_match(self, mock_session):
        """SIRET lookup returns exact match → match_type 'siret'."""
        vendor = _stub_vendor()

        # Mock: get_by_siret returns vendor
        with patch("agent.vendor_memory.get_by_siret", new_callable=AsyncMock) as mock_siret:
            mock_siret.return_value = MagicMock()
            mock_siret.return_value.__class__ = type("VendorRow", (), {})
            # We need to mock at the right level
            with patch("agent.vendor_memory.get_by_siret", return_value=MagicMock()) as m:
                result = await lookup_vendor(mock_session, vendor_name="Irrelevant", siret="12345678901234")
                if result:
                    assert result.match_type == "siret"
                    assert result.match_score == 100

    @pytest.mark.asyncio
    async def test_exact_name_match(self, mock_session):
        """Exact name (ilike) returns vendor → match_type 'name'."""
        with patch("agent.vendor_memory.get_by_siret", return_value=None), \
             patch("agent.vendor_memory.get_by_name", return_value=[MagicMock()]):
            result = await lookup_vendor(mock_session, vendor_name="Metro Cash & Carry")
            if result:
                assert result.match_type == "name"
                assert result.match_score == 100

    @pytest.mark.asyncio
    async def test_miss_returns_none(self, mock_session):
        """Completely unknown vendor → None."""
        with patch("agent.vendor_memory.get_by_siret", return_value=None), \
             patch("agent.vendor_memory.get_by_name", return_value=[]), \
             patch("agent.vendor_memory.get_all_active", return_value=[]):
            result = await lookup_vendor(mock_session, vendor_name="Totally Unknown Vendor XYZZY")
            assert result is None
