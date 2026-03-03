"""Google Sheets client — read budget data from Budget_Suivi spreadsheet."""

from __future__ import annotations

import json
from decimal import Decimal

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from agent.config import settings
from agent.logging import get_logger

logger = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


class SheetsClient:
    """Read-only access to the budget tracking spreadsheet."""

    def __init__(self) -> None:
        self._service = None

    def _get_service(self):
        if self._service is None:
            creds_info = json.loads(settings.google_service_account_json)
            creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
            self._service = build("sheets", "v4", credentials=creds)
        return self._service

    async def get_budget_remaining(
        self, cost_center: str, gl_account: str, month: int
    ) -> Decimal | None:
        """Look up remaining budget for a cost center + GL account + month.

        Returns the remaining budget amount, or None if no entry found.
        The sheet structure is expected to be:
        | Cost Center | GL Account | Month | Budget | Spent | Remaining |
        """
        service = self._get_service()

        try:
            # Read entire budget sheet (assumed to be first sheet)
            result = (
                service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=settings.google_budget_sheet_id,
                    range="A:F",
                )
                .execute()
            )
            rows = result.get("values", [])

            if not rows:
                logger.warning("budget_sheet_empty")
                return None

            # Skip header
            for row in rows[1:]:
                if len(row) < 6:
                    continue

                row_cc = str(row[0]).strip()
                row_gl = str(row[1]).strip()
                row_month = int(row[2])

                if row_cc == cost_center and row_gl == gl_account and row_month == month:
                    remaining = Decimal(str(row[5]).replace(",", ".").replace(" ", ""))
                    logger.info(
                        "budget_found",
                        cost_center=cost_center,
                        gl_account=gl_account,
                        month=month,
                        remaining=str(remaining),
                    )
                    return remaining

            logger.info(
                "budget_not_found",
                cost_center=cost_center,
                gl_account=gl_account,
                month=month,
            )
            return None

        except Exception as exc:
            logger.error("budget_read_error", error=str(exc))
            return None
