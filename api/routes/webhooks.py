"""Webhook endpoints — Gmail Pub/Sub push notifications."""

from __future__ import annotations

import base64
import json

from fastapi import APIRouter, Request

from agent.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/gmail")
async def gmail_push_notification(request: Request):
    """Receive Gmail Pub/Sub push notification when a new email arrives.

    Google sends a POST with:
    {
        "message": {
            "data": "<base64 encoded>",
            "messageId": "...",
            "publishTime": "..."
        },
        "subscription": "..."
    }
    """
    body = await request.json()

    try:
        message = body.get("message", {})
        data = message.get("data", "")
        decoded = json.loads(base64.b64decode(data).decode("utf-8"))

        email_address = decoded.get("emailAddress", "")
        history_id = decoded.get("historyId", "")

        logger.info(
            "gmail_notification_received",
            email=email_address,
            history_id=history_id,
        )

        # TODO: Phase 1 — trigger ingestion pipeline
        # await ingestion_pipeline.process_new_emails(history_id)

    except Exception as exc:
        logger.error("gmail_notification_error", error=str(exc))

    # Always return 200 to acknowledge to Google (prevent retries)
    return {"status": "ok"}
