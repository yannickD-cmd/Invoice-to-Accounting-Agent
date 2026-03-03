"""Gmail listener — handles Pub/Sub notifications and polls for new invoices."""

from __future__ import annotations

from agent.clients.gmail_client import GmailClient, IncomingEmail
from agent.logging import get_logger
from agent.pipeline import process_incoming_email

logger = get_logger(__name__)

gmail = GmailClient()


async def handle_gmail_notification(history_id: str) -> None:
    """Called when a Gmail Pub/Sub notification arrives.

    Fetches new emails since history_id and kicks off processing for each.
    """
    try:
        emails = await gmail.get_new_messages(history_id=history_id)
        logger.info("gmail_listener_triggered", history_id=history_id, emails_found=len(emails))

        for email in emails:
            await process_incoming_email(email)

    except Exception as exc:
        logger.error("gmail_listener_error", history_id=history_id, error=str(exc))


async def poll_inbox() -> None:
    """Manual poll — used as fallback if Pub/Sub is not active."""
    try:
        emails = await gmail.get_new_messages()
        logger.info("gmail_poll_complete", emails_found=len(emails))

        for email in emails:
            await process_incoming_email(email)

    except Exception as exc:
        logger.error("gmail_poll_error", error=str(exc))
