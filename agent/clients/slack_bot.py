"""Slack Bot — Bolt app with Socket Mode for approval interactions."""

from __future__ import annotations

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from agent.config import settings
from agent.logging import get_logger

logger = get_logger(__name__)

# ── Slack App Initialization ───────────────────────────────────────────────

slack_app = AsyncApp(token=settings.slack_bot_token)


# ── Block Kit Message Builders ─────────────────────────────────────────────


def build_approval_message(
    invoice_summary: dict,
    job_id: str,
    flags: list[str] | None = None,
) -> list[dict]:
    """Build a Slack Block Kit message for invoice approval.

    invoice_summary keys: vendor_name, invoice_number, total_ttc, cost_center,
                          gl_account, invoice_date, due_date
    """
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📄 Facture à approuver"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Fournisseur:*\n{invoice_summary['vendor_name']}"},
                {"type": "mrkdwn", "text": f"*N° Facture:*\n{invoice_summary['invoice_number']}"},
                {"type": "mrkdwn", "text": f"*Montant TTC:*\n€{invoice_summary['total_ttc']}"},
                {"type": "mrkdwn", "text": f"*Centre de coût:*\n{invoice_summary['cost_center']}"},
                {"type": "mrkdwn", "text": f"*Compte GL:*\n{invoice_summary['gl_account']}"},
                {"type": "mrkdwn", "text": f"*Date:*\n{invoice_summary['invoice_date']}"},
            ],
        },
    ]

    # Add warning banner if there are flags
    if flags:
        flag_text = "\n".join(f"⚠️ {f}" for f in flags)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Alertes:*\n{flag_text}"},
        })

    # Action buttons
    blocks.append({
        "type": "actions",
        "block_id": "approval_actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "✅ Approuver"},
                "style": "primary",
                "action_id": "approve_invoice",
                "value": job_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "❌ Rejeter"},
                "style": "danger",
                "action_id": "reject_invoice",
                "value": job_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "✏️ Modifier"},
                "action_id": "edit_invoice",
                "value": job_id,
            },
        ],
    })

    return blocks


def build_exception_message(
    exception_type: str,
    details: dict,
    job_id: str,
) -> list[dict]:
    """Build a Slack message for an exception notification."""
    type_labels = {
        "DUPLICATE": "🔄 Facture en double détectée",
        "UNKNOWN_VENDOR": "❓ Fournisseur inconnu",
        "LOW_CONFIDENCE": "🔍 Extraction incertaine",
        "VAT_FLAG": "💰 Anomalie TVA détectée",
        "BUDGET_EXCEEDED": "📊 Dépassement de budget",
        "AMBIGUOUS_CC": "🏨 Centre de coût ambigu",
        "MATH_ERROR": "🧮 Erreur de calcul détectée",
    }

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": type_labels.get(exception_type, "⚠️ Exception")},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(f"*{k}:* {v}" for k, v in details.items()),
            },
        },
    ]

    # Add action buttons based on exception type
    elements = []
    if exception_type == "UNKNOWN_VENDOR":
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "➕ Créer fournisseur"},
            "style": "primary",
            "action_id": "create_vendor",
            "value": job_id,
        })
    elif exception_type == "DUPLICATE":
        elements.extend([
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🗑️ Ignorer"},
                "action_id": "dismiss_duplicate",
                "value": job_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "⚡ Forcer le traitement"},
                "style": "danger",
                "action_id": "force_process",
                "value": job_id,
            },
        ])

    if elements:
        blocks.append({"type": "actions", "elements": elements})

    return blocks


# ── Interaction Handlers ───────────────────────────────────────────────────


@slack_app.action("approve_invoice")
async def handle_approve(ack, body, client):
    await ack()
    job_id = body["actions"][0]["value"]
    user_id = body["user"]["id"]
    logger.info("invoice_approved_via_slack", job_id=job_id, user=user_id)

    # TODO: Phase 3 — trigger output pipeline
    # await approval_engine.process_approval(job_id, user_id)

    await client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text=f"✅ Facture approuvée par <@{user_id}>",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ *Facture approuvée* par <@{user_id}>",
                },
            }
        ],
    )


@slack_app.action("reject_invoice")
async def handle_reject(ack, body, client):
    await ack()
    job_id = body["actions"][0]["value"]
    user_id = body["user"]["id"]
    logger.info("invoice_rejected_via_slack", job_id=job_id, user=user_id)

    # TODO: Phase 3 — open rejection reason modal
    # For now, reject directly
    await client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text=f"❌ Facture rejetée par <@{user_id}>",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"❌ *Facture rejetée* par <@{user_id}>",
                },
            }
        ],
    )


@slack_app.action("edit_invoice")
async def handle_edit(ack, body, client):
    await ack()
    job_id = body["actions"][0]["value"]
    user_id = body["user"]["id"]
    logger.info("invoice_edit_requested", job_id=job_id, user=user_id)

    # TODO: Phase 3 — open field-correction modal
    # await show_edit_modal(client, body["trigger_id"], job_id)


@slack_app.action("create_vendor")
async def handle_create_vendor(ack, body, client):
    await ack()
    job_id = body["actions"][0]["value"]
    user_id = body["user"]["id"]
    logger.info("vendor_creation_requested", job_id=job_id, user=user_id)

    # TODO: Phase 3 — open vendor creation modal


@slack_app.action("dismiss_duplicate")
async def handle_dismiss_duplicate(ack, body, client):
    await ack()
    job_id = body["actions"][0]["value"]
    user_id = body["user"]["id"]
    logger.info("duplicate_dismissed", job_id=job_id, user=user_id)

    await client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text=f"🗑️ Doublon ignoré par <@{user_id}>",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🗑️ *Doublon ignoré* par <@{user_id}>",
                },
            }
        ],
    )


@slack_app.action("force_process")
async def handle_force_process(ack, body, client):
    await ack()
    job_id = body["actions"][0]["value"]
    user_id = body["user"]["id"]
    logger.info("duplicate_force_processed", job_id=job_id, user=user_id)

    # TODO: Phase 5 — reprocess with duplicate override


# ── Posting Helpers ────────────────────────────────────────────────────────


async def post_approval_request(channel: str, blocks: list[dict]) -> str | None:
    """Post an approval message and return the message timestamp."""
    try:
        result = await slack_app.client.chat_postMessage(
            channel=channel,
            text="Nouvelle facture à approuver",
            blocks=blocks,
        )
        return result.get("ts")
    except Exception as exc:
        logger.error("slack_post_failed", channel=channel, error=str(exc))
        return None


async def post_to_channel(channel: str, text: str, blocks: list[dict] | None = None) -> None:
    """Post a simple message to a channel."""
    try:
        await slack_app.client.chat_postMessage(
            channel=channel,
            text=text,
            blocks=blocks,
        )
    except Exception as exc:
        logger.error("slack_post_failed", channel=channel, error=str(exc))


# ── Socket Mode Runner ────────────────────────────────────────────────────


async def start_slack_bot() -> None:
    """Start the Slack bot in Socket Mode (called from app lifespan)."""
    if not settings.slack_app_token:
        logger.warning("slack_not_configured", reason="SLACK_APP_TOKEN missing")
        return

    handler = AsyncSocketModeHandler(slack_app, settings.slack_app_token)
    logger.info("slack_bot_starting")
    await handler.start_async()
