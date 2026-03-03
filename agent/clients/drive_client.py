"""Google Drive client — upload, rename, move PDFs, create folders."""

from __future__ import annotations

import json
from io import BytesIO

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from agent.config import settings
from agent.constants import COST_CENTER_FOLDERS, PROPERTIES_BY_CC
from agent.logging import get_logger

logger = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class DriveClient:
    """Wrapper around the Google Drive API for invoice filing."""

    def __init__(self) -> None:
        self._service = None

    def _get_service(self):
        if self._service is None:
            creds_info = json.loads(settings.google_service_account_json)
            creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
            self._service = build("drive", "v3", credentials=creds)
        return self._service

    async def upload_to_inbox_raw(self, filename: str, pdf_data: bytes) -> str:
        """Upload a PDF to /INBOX_RAW. Returns the Drive file ID."""
        service = self._get_service()

        # Find or create INBOX_RAW folder
        inbox_folder_id = await self._find_or_create_folder(
            "INBOX_RAW", settings.google_drive_root_folder_id
        )

        media = MediaIoBaseUpload(BytesIO(pdf_data), mimetype="application/pdf")
        file_metadata = {
            "name": filename,
            "parents": [inbox_folder_id],
        }
        result = service.files().create(
            body=file_metadata, media_body=media, fields="id"
        ).execute()

        file_id = result["id"]
        logger.info("drive_uploaded", filename=filename, file_id=file_id, folder="INBOX_RAW")
        return file_id

    async def file_invoice(
        self,
        drive_file_id: str,
        cost_center: str,
        vendor_code: str,
        invoice_number: str,
        invoice_date: str,
        year: str | None = None,
    ) -> str:
        """Rename and move a PDF from INBOX_RAW to the correct property folder.

        Naming: YYYY-MM-DD_VendorCode_InvoiceNumber_CostCenter.pdf
        Target: /YYYY/CC-XX_PropertyName/
        Returns the new Drive file path.
        """
        if year is None:
            year = invoice_date[:4]

        new_name = f"{invoice_date}_{vendor_code}_{invoice_number}_{cost_center}.pdf"

        # Ensure year folder exists
        year_folder_id = await self._find_or_create_folder(
            year, settings.google_drive_root_folder_id
        )

        # Ensure cost center folder exists under year
        cc_folder_name = COST_CENTER_FOLDERS.get(cost_center, cost_center)
        cc_folder_id = await self._find_or_create_folder(cc_folder_name, year_folder_id)

        # Rename + move
        service = self._get_service()

        # Get current parent to remove
        current = service.files().get(fileId=drive_file_id, fields="parents").execute()
        current_parents = ",".join(current.get("parents", []))

        service.files().update(
            fileId=drive_file_id,
            body={"name": new_name},
            addParents=cc_folder_id,
            removeParents=current_parents,
            fields="id, parents",
        ).execute()

        drive_path = f"/{year}/{cc_folder_name}/{new_name}"
        logger.info("drive_filed", file_id=drive_file_id, path=drive_path)
        return drive_path

    async def move_to_exceptions(
        self, drive_file_id: str, reason_prefix: str, original_name: str
    ) -> str:
        """Move a file to /EXCEPTIONS/ with a reason prefix."""
        service = self._get_service()

        exceptions_folder_id = await self._find_or_create_folder(
            "EXCEPTIONS", settings.google_drive_root_folder_id
        )

        new_name = f"{reason_prefix}_{original_name}"

        current = service.files().get(fileId=drive_file_id, fields="parents").execute()
        current_parents = ",".join(current.get("parents", []))

        service.files().update(
            fileId=drive_file_id,
            body={"name": new_name},
            addParents=exceptions_folder_id,
            removeParents=current_parents,
            fields="id, parents",
        ).execute()

        logger.info("drive_exception_filed", file_id=drive_file_id, reason=reason_prefix)
        return f"/EXCEPTIONS/{new_name}"

    async def _find_or_create_folder(self, name: str, parent_id: str) -> str:
        """Find a folder by name under a parent, or create it."""
        service = self._get_service()

        query = (
            f"name='{name}' and '{parent_id}' in parents "
            f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
        )
        results = service.files().list(q=query, fields="files(id)").execute()
        files = results.get("files", [])

        if files:
            return files[0]["id"]

        # Create folder
        metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        folder = service.files().create(body=metadata, fields="id").execute()
        logger.info("drive_folder_created", name=name, folder_id=folder["id"])
        return folder["id"]
