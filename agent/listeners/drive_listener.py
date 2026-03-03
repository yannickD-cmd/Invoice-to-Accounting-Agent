"""Drive listener — polls INBOX_RAW for manually uploaded PDFs."""

from __future__ import annotations

import json

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from agent.config import settings
from agent.logging import get_logger

logger = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


async def poll_inbox_raw() -> list[dict]:
    """Poll Google Drive INBOX_RAW folder for new PDF files.

    Returns a list of dicts with file_id, filename, and data bytes.
    Files are identified by a custom property to avoid reprocessing.
    """
    try:
        creds_info = json.loads(settings.google_service_account_json)
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        service = build("drive", "v3", credentials=creds)

        # Find INBOX_RAW folder
        query = (
            f"name='INBOX_RAW' and '{settings.google_drive_root_folder_id}' in parents "
            "and mimeType='application/vnd.google-apps.folder' and trashed=false"
        )
        folders = service.files().list(q=query, fields="files(id)").execute()
        folder_files = folders.get("files", [])

        if not folder_files:
            logger.info("inbox_raw_not_found")
            return []

        inbox_id = folder_files[0]["id"]

        # List PDF files in INBOX_RAW that haven't been processed
        file_query = (
            f"'{inbox_id}' in parents "
            "and mimeType='application/pdf' "
            "and trashed=false"
        )
        results = service.files().list(
            q=file_query,
            fields="files(id, name, createdTime, appProperties)",
            orderBy="createdTime",
        ).execute()

        files = results.get("files", [])
        new_files = []

        for f in files:
            props = f.get("appProperties", {})
            if props.get("processed") == "true":
                continue

            new_files.append({
                "file_id": f["id"],
                "filename": f["name"],
            })

        logger.info("inbox_raw_polled", total=len(files), new=len(new_files))
        return new_files

    except Exception as exc:
        logger.error("inbox_raw_poll_error", error=str(exc))
        return []


async def mark_as_processed(file_id: str) -> None:
    """Mark a file in INBOX_RAW as processed to avoid reprocessing."""
    try:
        creds_info = json.loads(settings.google_service_account_json)
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        service = build("drive", "v3", credentials=creds)

        service.files().update(
            fileId=file_id,
            body={"appProperties": {"processed": "true"}},
        ).execute()

        logger.info("inbox_raw_marked_processed", file_id=file_id)

    except Exception as exc:
        logger.error("inbox_raw_mark_error", file_id=file_id, error=str(exc))
