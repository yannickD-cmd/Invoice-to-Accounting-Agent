"""Gmail API client — read emails, download attachments, send escalation emails."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from email.utils import parseaddr

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from agent.config import settings
from agent.logging import get_logger

logger = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


@dataclass
class EmailAttachment:
    filename: str
    data: bytes
    mime_type: str


@dataclass
class IncomingEmail:
    message_id: str
    sender: str
    subject: str
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    body_text: str = ""
    attachments: list[EmailAttachment] = field(default_factory=list)
    is_forwarded: bool = False
    original_sender: str | None = None


class GmailClient:
    """Wrapper around the Gmail API for the shared AP inbox."""

    def __init__(self) -> None:
        self._service = None

    def _get_service(self):
        if self._service is None:
            import json

            creds_info = json.loads(settings.google_service_account_json)
            creds = Credentials.from_service_account_info(
                creds_info,
                scopes=SCOPES,
                subject=settings.gmail_ap_inbox,  # Impersonate the AP inbox
            )
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    async def get_new_messages(self, history_id: str | None = None) -> list[IncomingEmail]:
        """Fetch new unread messages from the AP inbox.

        If history_id is provided, use history.list for incremental sync.
        Otherwise, list recent unread messages.
        """
        service = self._get_service()
        emails: list[IncomingEmail] = []

        if history_id:
            # Incremental: get messages added since history_id
            results = (
                service.users()
                .history()
                .list(userId="me", startHistoryId=history_id, historyTypes=["messageAdded"])
                .execute()
            )
            message_ids = []
            for record in results.get("history", []):
                for msg in record.get("messagesAdded", []):
                    message_ids.append(msg["message"]["id"])
        else:
            # Full scan: get recent unread with attachments
            results = (
                service.users()
                .messages()
                .list(userId="me", q="is:unread has:attachment", maxResults=20)
                .execute()
            )
            message_ids = [m["id"] for m in results.get("messages", [])]

        for msg_id in message_ids:
            try:
                email = await self._parse_message(msg_id)
                if email and email.attachments:
                    emails.append(email)
            except Exception as exc:
                logger.error("gmail_parse_error", message_id=msg_id, error=str(exc))

        logger.info("gmail_fetched", count=len(emails))
        return emails

    async def _parse_message(self, message_id: str) -> IncomingEmail | None:
        """Parse a single Gmail message into our IncomingEmail model."""
        service = self._get_service()
        msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()

        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}

        sender = headers.get("from", "")
        subject = headers.get("subject", "")
        to_raw = headers.get("to", "")
        cc_raw = headers.get("cc", "")

        # Parse To and CC into email lists
        to_addrs = [parseaddr(a)[1] for a in to_raw.split(",") if parseaddr(a)[1]]
        cc_addrs = [parseaddr(a)[1] for a in cc_raw.split(",") if parseaddr(a)[1]]

        # Detect forwarded emails
        is_forwarded = any(
            marker in subject.lower()
            for marker in ["fwd:", "fw:", "tr:", "transféré:"]
        )

        # Extract attachments
        attachments = self._extract_attachments(msg, message_id)

        return IncomingEmail(
            message_id=msg["id"],
            sender=parseaddr(sender)[1],
            subject=subject,
            to=to_addrs,
            cc=cc_addrs,
            attachments=attachments,
            is_forwarded=is_forwarded,
        )

    def _extract_attachments(self, msg: dict, message_id: str) -> list[EmailAttachment]:
        """Extract PDF attachments from a Gmail message."""
        attachments: list[EmailAttachment] = []
        parts = msg.get("payload", {}).get("parts", [])

        for part in parts:
            filename = part.get("filename", "")
            mime_type = part.get("mimeType", "")

            if not filename or "pdf" not in mime_type.lower():
                continue

            attachment_id = part.get("body", {}).get("attachmentId")
            if not attachment_id:
                continue

            service = self._get_service()
            att = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )

            data = base64.urlsafe_b64decode(att["data"])
            attachments.append(
                EmailAttachment(filename=filename, data=data, mime_type=mime_type)
            )

        return attachments

    async def send_email(self, to: str, subject: str, body: str) -> None:
        """Send an escalation email from the AP inbox."""
        import base64
        from email.mime.text import MIMEText

        message = MIMEText(body, "html")
        message["to"] = to
        message["from"] = settings.gmail_ap_inbox
        message["subject"] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service = self._get_service()

        try:
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            logger.info("email_sent", to=to, subject=subject)
        except Exception as exc:
            logger.error("email_send_failed", to=to, error=str(exc))
            raise
