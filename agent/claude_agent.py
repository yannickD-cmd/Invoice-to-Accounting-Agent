"""Claude AI agent for structured invoice data extraction."""

from __future__ import annotations

from pathlib import Path

import anthropic

from agent.config import settings
from agent.logging import get_logger
from agent.models.invoice import InvoiceData

logger = get_logger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _detect_language(text: str) -> str:
    """Simple heuristic: if French keywords are present → 'fr', else 'en'."""
    french_keywords = [
        "facture", "tva", " ht", " ttc", "montant", "fournisseur",
        "échéance", "réglement", "avoir", "bon de commande",
    ]
    text_lower = text.lower()
    french_hits = sum(1 for kw in french_keywords if kw in text_lower)
    return "fr" if french_hits >= 2 else "en"


def _load_prompt(language: str) -> str:
    """Load the extraction system prompt for the given language."""
    filename = f"extraction_{language}.md"
    path = PROMPTS_DIR / filename
    if not path.exists():
        logger.warning("prompt_not_found", filename=filename, falling_back="extraction_fr.md")
        path = PROMPTS_DIR / "extraction_fr.md"
    return path.read_text(encoding="utf-8")


async def extract_invoice_with_claude(raw_text: str) -> InvoiceData:
    """Send invoice text to Claude and receive structured InvoiceData.

    Steps:
    1. Detect language (French vs English)
    2. Load appropriate system prompt
    3. Inject InvoiceData JSON schema into prompt
    4. Call Claude with temperature=0 for deterministic extraction
    5. Parse and validate response into InvoiceData model

    Raises ValueError if Claude returns invalid or unparseable data.
    """
    language = _detect_language(raw_text)
    system_prompt_template = _load_prompt(language)

    # Inject the Pydantic schema into the prompt
    schema_json = InvoiceData.model_json_schema()
    system_prompt = system_prompt_template.replace("{schema}", str(schema_json))

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    logger.info(
        "claude_extraction_starting",
        language=language,
        text_length=len(raw_text),
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": f"Extrais les données de cette facture:\n\n{raw_text}",
                }
            ],
            temperature=0.0,
        )

        response_text = response.content[0].text

        # Remove markdown code fences if present
        if response_text.strip().startswith("```"):
            lines = response_text.strip().split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            response_text = "\n".join(lines)

        parsed = InvoiceData.model_validate_json(response_text)

        logger.info(
            "claude_extraction_complete",
            vendor=parsed.vendor_name,
            total_ttc=str(parsed.total_ttc),
            confidence=parsed.raw_confidence,
            low_confidence_fields=parsed.low_confidence_fields,
        )

        return parsed

    except anthropic.APIError as exc:
        logger.error("claude_api_error", error=str(exc))
        raise
    except Exception as exc:
        logger.error("claude_parse_error", error=str(exc))
        raise ValueError(f"Failed to parse Claude response: {exc}") from exc
