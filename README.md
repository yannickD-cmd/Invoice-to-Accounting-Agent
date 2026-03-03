# Invoice-to-Accounting Agent

An AI-powered agent that automatically extracts, classifies, and processes invoices into structured accounting entries — eliminating manual data entry and reducing errors in financial workflows.

## Overview

This agent accepts invoices in various formats (PDF, image, email attachment) and produces structured accounting output ready for import into bookkeeping systems such as QuickBooks, Xero, or any ERP via CSV/JSON export.

```
Invoice (PDF/Image) ──▶ AI Agent ──▶ Structured Accounting Entry
                          │
                          ├─ Extract: vendor, date, line items, totals, tax
                          ├─ Classify: expense category, GL account code
                          └─ Output: JSON / CSV / API push
```

## Features

- **Invoice parsing** — Extracts key fields from PDFs and scanned images using OCR + LLM
- **Line-item extraction** — Captures individual line items, quantities, unit prices, and taxes
- **GL account classification** — Maps expenses to the correct general ledger accounts automatically
- **Duplicate detection** — Flags invoices already processed based on vendor + date + amount
- **Multi-format output** — Exports to JSON, CSV, or pushes directly to accounting APIs
- **Human-in-the-loop review** — Confidence scoring with a review queue for low-confidence extractions

## Tech Stack

| Layer | Technology |
|---|---|
| AI / LLM | Claude (Anthropic API) |
| Orchestration | Claude Agent SDK |
| OCR | Tesseract / AWS Textract |
| Backend | Python (FastAPI) |
| Storage | PostgreSQL |
| Queue | Redis / Celery |

## Project Structure

```
Invoice-to-Accounting-Agent/
├── agent/
│   ├── extractor.py        # Invoice field extraction logic
│   ├── classifier.py       # GL account classification
│   ├── validator.py        # Data validation and dedup
│   └── tools.py            # Agent tool definitions
├── api/
│   ├── main.py             # FastAPI entrypoint
│   └── routes/             # API route handlers
├── prompts/
│   └── extraction.md       # System prompts for the agent
├── tests/
│   └── sample_invoices/    # Test fixtures
├── .env.example
├── requirements.txt
└── README.md
```

## Getting Started

### Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)

### Installation

```bash
git clone https://github.com/yannickD-cmd/Invoice-to-Accounting-Agent.git
cd Invoice-to-Accounting-Agent

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
```

### Run

```bash
uvicorn api.main:app --reload
```

## Usage

```python
from agent.extractor import process_invoice

result = process_invoice("invoices/acme_invoice_2024.pdf")
print(result)
# {
#   "vendor": "Acme Corp",
#   "invoice_date": "2024-11-15",
#   "total": 1250.00,
#   "tax": 100.00,
#   "line_items": [...],
#   "gl_account": "6200 - Office Supplies",
#   "confidence": 0.97
# }
```

## Roadmap

- [ ] PDF and image ingestion pipeline
- [ ] LLM-based field extraction with Claude
- [ ] GL account classification model
- [ ] REST API with FastAPI
- [ ] CSV / QuickBooks IIF export
- [ ] Xero and QuickBooks Online direct integration
- [ ] Web UI for review queue
- [ ] Multi-currency support

## License

MIT
