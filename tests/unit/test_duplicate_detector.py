"""Unit tests for the duplicate detector."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.duplicate_detector import DuplicateResult, check_duplicate


@pytest.fixture
def mock_session():
    session = AsyncMock()
    return session


class TestDuplicateDetector:

    @pytest.mark.asyncio
    async def test_no_vendor_id_returns_unique(self, mock_session):
        """If vendor_id is None (unknown vendor), always return UNIQUE."""
        result = await check_duplicate(
            mock_session,
            vendor_id=None,
            invoice_number="F-001",
            total_ttc=Decimal("100.00"),
            invoice_date=date(2025, 6, 1),
        )
        assert result.result == DuplicateResult.UNIQUE

    @pytest.mark.asyncio
    async def test_confirmed_duplicate(self, mock_session):
        """Exact match on vendor + invoice# + amount → CONFIRMED."""
        original_id = uuid4()
        mock_row = MagicMock()
        mock_row.id = original_id
        mock_row.invoice_number = "F-001"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row
        mock_session.execute.return_value = mock_result

        result = await check_duplicate(
            mock_session,
            vendor_id=uuid4(),
            invoice_number="F-001",
            total_ttc=Decimal("500.00"),
            invoice_date=date(2025, 6, 1),
        )
        assert result.result == DuplicateResult.CONFIRMED_DUPLICATE
        assert result.original_invoice_id == original_id

    @pytest.mark.asyncio
    async def test_unique_invoice(self, mock_session):
        """No match at all → UNIQUE."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await check_duplicate(
            mock_session,
            vendor_id=uuid4(),
            invoice_number="F-NEW",
            total_ttc=Decimal("300.00"),
            invoice_date=date(2025, 6, 15),
        )
        assert result.result == DuplicateResult.UNIQUE
