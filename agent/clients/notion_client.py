"""Notion API client — log audit entries, manage vendor and pending invoice databases."""

from __future__ import annotations

from datetime import datetime

from notion_client import AsyncClient

from agent.config import settings
from agent.logging import get_logger

logger = get_logger(__name__)


class NotionLogger:
    """Manages the three Notion databases: Fournisseurs, Factures en attente, Journal d'audit."""

    def __init__(self) -> None:
        self._client: AsyncClient | None = None

    def _get_client(self) -> AsyncClient:
        if self._client is None:
            self._client = AsyncClient(auth=settings.notion_token)
        return self._client

    # ── Journal d'audit (Audit Log) ────────────────────────────────────

    async def write_audit_entry(
        self,
        job_id: str,
        action: str,
        actor: str = "system",
        details: str = "",
        invoice_number: str = "",
        vendor_name: str = "",
        cost_center: str = "",
    ) -> None:
        """Write an immutable audit log entry to the Journal d'audit database."""
        client = self._get_client()

        try:
            await client.pages.create(
                parent={"database_id": settings.notion_db_audit},
                properties={
                    "Job ID": {"title": [{"text": {"content": job_id}}]},
                    "Action": {"select": {"name": action}},
                    "Acteur": {"rich_text": [{"text": {"content": actor}}]},
                    "Détails": {"rich_text": [{"text": {"content": details[:2000]}}]},
                    "N° Facture": {"rich_text": [{"text": {"content": invoice_number}}]},
                    "Fournisseur": {"rich_text": [{"text": {"content": vendor_name}}]},
                    "Centre de coût": {"select": {"name": cost_center}} if cost_center else {"select": None},
                    "Date": {"date": {"start": datetime.utcnow().isoformat()}},
                },
            )
            logger.info("notion_audit_logged", job_id=job_id, action=action)
        except Exception as exc:
            logger.error("notion_audit_failed", job_id=job_id, error=str(exc))

    # ── Factures en attente (Pending Invoices) ─────────────────────────

    async def create_pending_invoice(
        self,
        job_id: str,
        exception_type: str,
        vendor_name: str = "",
        invoice_number: str = "",
        total_ttc: str = "",
        cost_center: str = "",
        owner: str = "",
        deadline_hours: int = 24,
    ) -> None:
        """Create an entry in the Factures en attente exception queue."""
        client = self._get_client()

        try:
            await client.pages.create(
                parent={"database_id": settings.notion_db_pending},
                properties={
                    "Job ID": {"title": [{"text": {"content": job_id}}]},
                    "Type d'exception": {"select": {"name": exception_type}},
                    "Fournisseur": {"rich_text": [{"text": {"content": vendor_name}}]},
                    "N° Facture": {"rich_text": [{"text": {"content": invoice_number}}]},
                    "Montant TTC": {"rich_text": [{"text": {"content": total_ttc}}]},
                    "Centre de coût": {"select": {"name": cost_center}} if cost_center else {"select": None},
                    "Responsable": {"rich_text": [{"text": {"content": owner}}]},
                    "Statut": {"select": {"name": "En attente"}},
                    "Délai (heures)": {"number": deadline_hours},
                },
            )
            logger.info("notion_pending_created", job_id=job_id, exception_type=exception_type)
        except Exception as exc:
            logger.error("notion_pending_failed", job_id=job_id, error=str(exc))

    # ── Fournisseurs (Vendors) ─────────────────────────────────────────

    async def sync_vendor(
        self,
        vendor_id: str,
        vendor_name: str,
        siret: str = "",
        default_gl: str = "",
        default_vat: str = "",
        cost_centers: str = "",
        payment_terms: str = "",
        notes: str = "",
    ) -> None:
        """Create or update a vendor in the Fournisseurs database."""
        client = self._get_client()

        try:
            # Check if vendor already exists in Notion
            existing = await client.databases.query(
                database_id=settings.notion_db_vendors,
                filter={
                    "property": "Vendor ID",
                    "rich_text": {"equals": vendor_id},
                },
            )

            properties = {
                "Nom": {"title": [{"text": {"content": vendor_name}}]},
                "Vendor ID": {"rich_text": [{"text": {"content": vendor_id}}]},
                "SIRET": {"rich_text": [{"text": {"content": siret}}]},
                "Compte GL": {"rich_text": [{"text": {"content": default_gl}}]},
                "TVA par défaut": {"rich_text": [{"text": {"content": default_vat}}]},
                "Centres de coût": {"rich_text": [{"text": {"content": cost_centers}}]},
                "Conditions de paiement": {"rich_text": [{"text": {"content": payment_terms}}]},
                "Notes": {"rich_text": [{"text": {"content": notes[:2000]}}]},
            }

            if existing["results"]:
                # Update existing
                page_id = existing["results"][0]["id"]
                await client.pages.update(page_id=page_id, properties=properties)
                logger.info("notion_vendor_updated", vendor_id=vendor_id)
            else:
                # Create new
                await client.pages.create(
                    parent={"database_id": settings.notion_db_vendors},
                    properties=properties,
                )
                logger.info("notion_vendor_created", vendor_id=vendor_id)

        except Exception as exc:
            logger.error("notion_vendor_sync_failed", vendor_id=vendor_id, error=str(exc))
