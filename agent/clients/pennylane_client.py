"""Pennylane API client — push invoices to the accounting system."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import httpx

from agent.config import settings
from agent.logging import get_logger

logger = get_logger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds


@dataclass
class PennylaneInvoicePayload:
    """Structured payload for the Pennylane invoice API."""

    invoice_number: str
    invoice_date: str        # YYYY-MM-DD
    due_date: str | None
    vendor_name: str
    vendor_siret: str | None
    subtotal_ht: Decimal
    vat_amount: Decimal
    total_ttc: Decimal
    gl_account: str
    vat_rate: Decimal
    currency: str = "EUR"
    line_items: list[dict] | None = None


class PennylaneClient:
    """REST client for the Pennylane API — one instance per entity."""

    def __init__(self) -> None:
        self._base_url = settings.pennylane_base_url

    async def push_invoice(
        self,
        cost_center: str,
        payload: PennylaneInvoicePayload,
        pdf_data: bytes,
        pdf_filename: str,
    ) -> str:
        """Push an invoice to the correct Pennylane entity.

        Returns the Pennylane invoice ID on success.
        Raises on failure after retries.
        """
        token = settings.pennylane_token_for(cost_center)

        headers = {
            "Authorization": f"Bearer {token}",
        }

        # Build multipart form
        invoice_json = {
            "invoice_number": payload.invoice_number,
            "date": payload.invoice_date,
            "due_date": payload.due_date,
            "supplier": {
                "name": payload.vendor_name,
                "siret": payload.vendor_siret,
            },
            "amount": {
                "subtotal": str(payload.subtotal_ht),
                "tax": str(payload.vat_amount),
                "total": str(payload.total_ttc),
                "currency": payload.currency,
            },
            "accounting": {
                "gl_account": payload.gl_account,
                "vat_rate": str(payload.vat_rate),
            },
        }

        if payload.line_items:
            invoice_json["line_items"] = payload.line_items

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{self._base_url}/supplier_invoices",
                        headers=headers,
                        files={"file": (pdf_filename, pdf_data, "application/pdf")},
                        data={"invoice": __import__("json").dumps(invoice_json)},
                    )

                    if response.status_code in (200, 201):
                        result = response.json()
                        pennylane_id = result.get("id", result.get("invoice_id", "unknown"))
                        logger.info(
                            "pennylane_pushed",
                            cost_center=cost_center,
                            pennylane_id=pennylane_id,
                            invoice_number=payload.invoice_number,
                        )
                        return str(pennylane_id)

                    logger.warning(
                        "pennylane_error",
                        status=response.status_code,
                        body=response.text[:500],
                        attempt=attempt + 1,
                    )
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"

            except httpx.TimeoutException as exc:
                logger.warning("pennylane_timeout", attempt=attempt + 1, error=str(exc))
                last_error = f"Timeout: {exc}"

            except Exception as exc:
                logger.warning("pennylane_request_error", attempt=attempt + 1, error=str(exc))
                last_error = str(exc)

            # Exponential backoff
            if attempt < MAX_RETRIES - 1:
                import asyncio

                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                await asyncio.sleep(wait)

        raise RuntimeError(f"Pennylane push failed after {MAX_RETRIES} attempts: {last_error}")
