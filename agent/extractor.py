"""PDF text extractor — pdfplumber with Tesseract OCR fallback."""

from __future__ import annotations

from io import BytesIO

import pdfplumber

from agent.logging import get_logger

logger = get_logger(__name__)


class ExtractionResult:
    """Result of PDF text extraction."""

    def __init__(self, text: str, method: str, page_count: int) -> None:
        self.text = text
        self.method = method  # "pdfplumber" or "ocr"
        self.page_count = page_count

    @property
    def is_empty(self) -> bool:
        return len(self.text.strip()) < 20


async def extract_text_from_pdf(pdf_data: bytes) -> ExtractionResult:
    """Extract text from a PDF. Tries pdfplumber first, falls back to OCR.

    Args:
        pdf_data: Raw PDF bytes.

    Returns:
        ExtractionResult with the full text and extraction method.
    """
    # Tier 1: pdfplumber for digitally-born PDFs
    text, page_count = _extract_with_pdfplumber(pdf_data)

    if text and len(text.strip()) > 50:
        logger.info("pdf_extracted", method="pdfplumber", pages=page_count, chars=len(text))
        return ExtractionResult(text=text, method="pdfplumber", page_count=page_count)

    # Tier 2: Tesseract OCR for scanned/image PDFs
    logger.info("pdf_pdfplumber_insufficient", chars=len(text.strip()), falling_back="ocr")
    text, page_count = _extract_with_ocr(pdf_data)

    if text and len(text.strip()) > 20:
        logger.info("pdf_extracted", method="ocr", pages=page_count, chars=len(text))
        return ExtractionResult(text=text, method="ocr", page_count=page_count)

    logger.warning("pdf_extraction_failed", reason="Both methods returned insufficient text")
    return ExtractionResult(text=text, method="ocr", page_count=page_count)


def _extract_with_pdfplumber(pdf_data: bytes) -> tuple[str, int]:
    """Extract text using pdfplumber (for digital PDFs)."""
    try:
        pages_text: list[str] = []
        with pdfplumber.open(BytesIO(pdf_data)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                pages_text.append(page_text)
        return "\n\n".join(pages_text), page_count
    except Exception as exc:
        logger.warning("pdfplumber_error", error=str(exc))
        return "", 0


def _extract_with_ocr(pdf_data: bytes) -> tuple[str, int]:
    """Extract text using Tesseract OCR (for scanned/image PDFs)."""
    try:
        import pytesseract
        from PIL import Image

        # Convert PDF pages to images, then OCR each
        # We use pdfplumber to get page images
        pages_text: list[str] = []
        with pdfplumber.open(BytesIO(pdf_data)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                img = page.to_image(resolution=300).original
                text = pytesseract.image_to_string(img, lang="fra+eng")
                pages_text.append(text)
        return "\n\n".join(pages_text), page_count
    except ImportError:
        logger.warning("ocr_not_available", reason="pytesseract not installed")
        return "", 0
    except Exception as exc:
        logger.warning("ocr_error", error=str(exc))
        return "", 0
