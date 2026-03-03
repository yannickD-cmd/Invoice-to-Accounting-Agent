# Implementation Plan — Invoice-to-Accounting Agent
## Hospitality Group · 6 Hotels + 2 Restaurants

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Component Breakdown](#2-component-breakdown)
3. [Data Flow — Happy Path](#3-data-flow--happy-path)
4. [Data Flow — Exception Paths](#4-data-flow--exception-paths)
5. [Database Schema](#5-database-schema)
6. [Integration Map](#6-integration-map)
7. [Approval Rules Engine](#7-approval-rules-engine)
8. [Vendor Memory & Learning Loop](#8-vendor-memory--learning-loop)
9. [Implementation Phases](#9-implementation-phases)
10. [File & Folder Structure](#10-file--folder-structure)
11. [Environment & Secrets](#11-environment--secrets)
12. [Open Questions Before Build](#12-open-questions-before-build)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        TRIGGER LAYER                            │
│   Gmail AP Inbox (watch)    │    Google Drive INBOX_RAW (poll)  │
└────────────┬────────────────┴────────────────┬──────────────────┘
             │                                  │
             ▼                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                      INGESTION LAYER                            │
│   • Download PDF attachment                                     │
│   • Deduplicate raw email (Message-ID check)                    │
│   • Store raw PDF in Google Drive /INBOX_RAW                    │
│   • Create job record in PostgreSQL (status: RECEIVED)          │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     EXTRACTION LAYER                            │
│   1. PDF → text (pdfplumber / Tesseract OCR fallback)           │
│   2. Claude API → structured JSON extraction                    │
│      Fields: vendor_name, siret, invoice_number, date,          │
│              due_date, subtotal, vat_breakdown[], total,        │
│              line_items[], currency, language                   │
│   3. Confidence score returned per field                        │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ENRICHMENT LAYER                             │
│   • Vendor Memory lookup (PostgreSQL)                           │
│     → match by SIRET > vendor_name fuzzy match > alias match    │
│     → resolve: GL account, VAT rate, cost center, pay terms     │
│   • Cost Center detection                                       │
│     → from email To/CC header > PDF content > vendor default    │
│   • VAT validation (cross-check extracted vs vendor default)    │
│   • Multi-line GL split (if line items span multiple accounts)  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    VALIDATION LAYER                             │
│   • Duplicate check: vendor_id + invoice_number + amount        │
│   • Math check: sum(line_items) == subtotal, subtotal+VAT==total│
│   • VAT edge case flags (insurance at 20%, mixed food VAT)      │
│   • Unrecognized vendor flag                                    │
│   • Budget check: query Budget_Suivi_2025.xlsx via Sheets API   │
│   → PASS: route to approval                                     │
│   → FAIL: route to exceptions                                   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    APPROVAL LAYER                               │
│   • Rules engine determines approver(s) and deadline            │
│   • Slack interactive message posted to #invoices-to-approve    │
│   • Approval state tracked in PostgreSQL                        │
│   • Escalation scheduler (APScheduler) checks overdue jobs      │
│   → APPROVED: proceed to output layer                           │
│   → REJECTED: log to Notion + notify + halt                     │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      OUTPUT LAYER                               │
│   • Push to Pennylane (REST API)                                │
│     → Select correct company entity (by cost center)           │
│     → POST invoice fields + attach PDF                          │
│   • File PDF in Google Drive                                    │
│     → Rename: YYYY-MM-DD_VendorCode_InvoiceNumber_CostCenter    │
│     → Move from INBOX_RAW to /YYYY/CC-XX_PropertyName/         │
│   • Write to Notion Audit Log                                   │
│   • Update job status → COMPLETED                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Breakdown

### 2.1 Email Listener (`agent/listeners/gmail_listener.py`)

- Uses Gmail API with push notifications (Pub/Sub) or polling fallback
- Watches shared AP inbox only
- Filters for emails with PDF attachments
- Extracts: sender, subject, To, CC headers (for property detection), attachment(s)
- Handles forwarded emails (detects original sender in body)
- Deduplicates by Gmail `Message-ID`
- Handles the "30% forwarded from property emails" problem by parsing `Forwarded message` headers

### 2.2 PDF Extractor (`agent/extractor.py`)

- **Tier 1 — pdfplumber**: for digitally-born PDFs (most software vendors)
- **Tier 2 — Tesseract OCR**: fallback for scanned/image PDFs
- Output: raw text + page layout metadata passed to Claude

### 2.3 Claude Extraction Agent (`agent/claude_agent.py`)

- Single structured extraction call to Claude
- Returns a typed `InvoiceData` Pydantic model
- System prompt enforces JSON output with per-field confidence scores
- Handles French and English invoices
- Special instructions for known edge cases (Metro multi-PDF, insurance VAT)
- If confidence on any critical field < 0.75 → flag for human review

```python
# InvoiceData model (simplified)
class InvoiceData(BaseModel):
    vendor_name: str
    vendor_name_confidence: float
    siret: str | None
    invoice_number: str
    invoice_date: date
    due_date: date | None
    subtotal_ht: Decimal
    vat_lines: list[VATLine]       # [{rate: 0.20, base: 100, amount: 20}]
    total_ttc: Decimal
    line_items: list[LineItem]     # [{description, qty, unit_price, gl_hint}]
    currency: str                  # EUR default
    language: str                  # fr / en
    raw_confidence: float          # overall extraction confidence
```

### 2.4 Vendor Memory (`agent/vendor_memory.py`)

- PostgreSQL table `vendors` (see schema below)
- Lookup priority: SIRET match → exact name → fuzzy alias match (rapidfuzz)
- On miss → create `UNKNOWN_VENDOR` record, trigger exception flow
- On correction (human approves with GL edit) → update vendor record
- Tracks `last_corrected_by`, `last_corrected_at` for learning loop

### 2.5 Cost Center Router (`agent/cost_center_router.py`)

Priority order for cost center detection:
1. Email `To:` or `CC:` header contains a property email → map to cost center
2. Invoice PDF content contains a property name/address → fuzzy match
3. Vendor default cost center (from vendor memory, if vendor always invoices one property)
4. Multiple matches → flag as ambiguous, request human selection in Slack

### 2.6 Duplicate Detector (`agent/duplicate_detector.py`)

- Check PostgreSQL `processed_invoices` table
- Match key: `(vendor_id, invoice_number, total_ttc)`
- Secondary check: `(vendor_id, invoice_date, total_ttc)` — catches Metro/Transgourmet number reuse
- Returns: UNIQUE / PROBABLE_DUPLICATE / CONFIRMED_DUPLICATE
- PROBABLE and CONFIRMED → routed to `#invoice-exceptions`

### 2.7 VAT Validator (`agent/vat_validator.py`)

Rules:
- Insurance vendors (GL 616000) → expected VAT = 0%, flag if 20% found in PDF
- Food vendors (GL 607100) → accept 5.5%, 10%, or mixed; verify math
- All others → expected 20%, flag deviations
- Always cross-check: `sum(vat_lines.amount) + subtotal_ht == total_ttc` (±0.02 rounding tolerance)

### 2.8 Budget Checker (`agent/budget_checker.py`)

- Reads `Budget_Suivi_2025.xlsx` via Google Sheets API (sheet is Excel but shared)
- Looks up `(cost_center, gl_account, month)` → remaining budget
- If invoice > 90% of remaining budget → soft warning in Slack message
- If invoice > remaining budget → hard flag, require Direction approval

### 2.9 Approval Engine (`agent/approval_engine.py`)

- Evaluates approval rules (see Section 7)
- Builds Slack Block Kit message with approve/reject/edit buttons
- Posts to `#invoices-to-approve`
- Stores approval request in `approval_requests` table with deadline
- Slack interaction handler processes button clicks → updates DB state

### 2.10 Pennylane Client (`agent/pennylane_client.py`)

- Token-based REST API client
- One API token per entity (8 tokens total) — stored in env/secrets vault
- Endpoint flow: `POST /invoices` with multipart (JSON fields + PDF binary)
- Maps cost center → Pennylane company ID
- Handles rate limits and retry with exponential backoff
- Stores Pennylane `invoice_id` in local DB for audit trail

### 2.11 Google Drive Filer (`agent/drive_filer.py`)

- Renames PDF to: `YYYY-MM-DD_VendorCode_InvoiceNumber_CostCenter.pdf`
- Moves from `/INBOX_RAW` to `/YYYY/CC-XX_PropertyName/`
- Creates year subfolder if missing
- On exception → moves to `/EXCEPTIONS/` with reason prefix: `DUPLICATE_`, `UNKNOWN_VENDOR_`, etc.

### 2.12 Notion Logger (`agent/notion_logger.py`)

Three Notion databases:

| Database | Purpose |
|---|---|
| Fournisseurs | Vendor memory admin view (synced from PostgreSQL) |
| Factures en attente | Exception queue + approval tracker (live state) |
| Journal d'audit | Immutable audit log of every action |

- Every state transition writes a row to Journal d'audit
- Exceptions create a row in Factures en attente with status and owner
- Vendor corrections from Slack sync back to Fournisseurs

### 2.13 Scheduler (`agent/scheduler.py`)

- APScheduler with PostgreSQL job store (persistent across Render restarts)
- Jobs:
  - `check_overdue_approvals` — runs every 30 minutes
  - `check_late_payments` — runs daily at 08:00
  - `sync_vendor_notion` — runs nightly at 02:00
  - `budget_report` — runs every Monday at 07:00 (posts to #finance-ops)

### 2.14 Slack Bot (`agent/slack_bot.py`)

- Slack Bolt SDK with Socket Mode (no public URL needed on Render free tier)
- Handles: `block_actions` (approve/reject buttons)
- On approve → triggers output layer pipeline
- On reject → asks for reason (modal), logs to Notion, notifies sender
- On edit → presents field-correction modal, updates vendor memory on submit

---

## 3. Data Flow — Happy Path

```
1. Supplier sends PDF invoice to AP inbox
2. Gmail Listener detects new email with attachment
3. PDF downloaded → stored in INBOX_RAW → job created (RECEIVED)
4. Extractor runs pdfplumber → text extracted
5. Claude agent extracts structured fields (confidence > 0.75 all fields)
6. Vendor Memory lookup → SIRET match → GL=615000, VAT=20%, CC=CC-03
7. Cost Center Router confirms CC-03 from email CC header
8. Duplicate Detector → UNIQUE
9. VAT Validator → math checks pass
10. Budget Checker → within budget
11. Approval Engine → amount=850€ → Marie, 48h deadline
12. Slack message posted to #invoices-to-approve with approve/reject buttons
13. Marie clicks Approve after 3 hours
14. Pennylane Client → POST to entity CC-03 → invoice_id=PL-9842 returned
15. Drive Filer → renames + moves to /2025/CC-03_VillaMargot/
16. Notion Logger → writes to Journal d'audit
17. Job status → COMPLETED
```

---

## 4. Data Flow — Exception Paths

### 4.1 Unrecognized Vendor
```
→ Vendor Memory lookup MISS
→ Exception: UNKNOWN_VENDOR
→ Drive Filer: moves to /EXCEPTIONS/ prefixed UNKNOWN_VENDOR_
→ Notion: creates row in Factures en attente (owner: Marie, deadline: 24h)
→ Slack: posts to #invoice-exceptions with vendor name found in PDF
→ Marie fills vendor details in Slack modal
→ Vendor Memory: new vendor record created
→ Invoice reprocessed from enrichment step
```

### 4.2 Duplicate Invoice
```
→ Duplicate Detector: CONFIRMED_DUPLICATE
→ Exception: DUPLICATE
→ Drive Filer: moves to /EXCEPTIONS/ prefixed DUPLICATE_
→ Slack: posts to #invoice-exceptions with link to original invoice
→ No Pennylane push
→ Notion: audit log entry with DUPLICATE status
→ Thomas investigates and either dismisses or force-processes
```

### 4.3 Low Confidence Extraction
```
→ Claude confidence < 0.75 on any critical field
→ Exception: LOW_CONFIDENCE
→ Slack: posts to #invoice-exceptions showing extracted data
  with flagged fields highlighted and edit buttons
→ Thomas/Marie corrects fields in Slack modal
→ Pipeline resumes from enrichment step with corrected data
```

### 4.4 VAT Mismatch
```
→ VAT Validator: insurance invoice shows 20% VAT
→ Exception: VAT_FLAG (soft, not blocking)
→ Slack approval message includes warning banner
→ Approver must explicitly acknowledge VAT flag before approving
```

### 4.5 Approval Timeout
```
→ Scheduler: deadline passed, no response
→ Escalation: posts to #finance-alerts
→ Email sent to Marie directly (via Gmail API)
→ Deadline extended +24h, notification to Direction if second timeout
```

### 4.6 Pennylane Push Failure
```
→ Pennylane Client: API error (4xx / 5xx)
→ Retry: exponential backoff x3
→ If still failing: job status → PUSH_FAILED
→ Slack: posts to #finance-ops with error details
→ PDF remains in INBOX_RAW (not moved)
→ Manual retry button in Slack
```

---

## 5. Database Schema

### `vendors`
```sql
id              UUID PRIMARY KEY
vendor_name     TEXT NOT NULL
aliases         TEXT[]          -- ["METRO Cash and Carry", "METRO France"]
siret           TEXT UNIQUE
default_gl      TEXT            -- "615000"
default_vat     DECIMAL(5,4)    -- 0.20
cost_centers    TEXT[]          -- ["CC-01", "CC-03"]
payment_terms   INTEGER         -- days: 30, 45, 0
notes           TEXT
is_active       BOOLEAN DEFAULT TRUE
last_corrected_by TEXT          -- Slack user ID
last_corrected_at TIMESTAMPTZ
created_at      TIMESTAMPTZ DEFAULT NOW()
```

### `processed_invoices`
```sql
id                UUID PRIMARY KEY
job_id            UUID REFERENCES jobs(id)
vendor_id         UUID REFERENCES vendors(id)
invoice_number    TEXT
invoice_date      DATE
due_date          DATE
cost_center       TEXT            -- "CC-03"
pennylane_entity  TEXT            -- Pennylane company ID
gl_account        TEXT
subtotal_ht       DECIMAL(12,2)
vat_amount        DECIMAL(12,2)
total_ttc         DECIMAL(12,2)
currency          TEXT DEFAULT 'EUR'
pennylane_id      TEXT            -- returned by Pennylane API
drive_file_id     TEXT
drive_path        TEXT
status            TEXT            -- COMPLETED / PUSH_FAILED / REJECTED
created_at        TIMESTAMPTZ DEFAULT NOW()
```

### `jobs`
```sql
id              UUID PRIMARY KEY
gmail_message_id TEXT UNIQUE
raw_drive_id    TEXT            -- file ID in INBOX_RAW
status          TEXT            -- RECEIVED / EXTRACTING / ENRICHING /
                                --   PENDING_APPROVAL / APPROVED / COMPLETED /
                                --   EXCEPTION / PUSH_FAILED
exception_type  TEXT            -- DUPLICATE / UNKNOWN_VENDOR / LOW_CONFIDENCE / VAT_FLAG
exception_note  TEXT
created_at      TIMESTAMPTZ DEFAULT NOW()
updated_at      TIMESTAMPTZ DEFAULT NOW()
```

### `approval_requests`
```sql
id              UUID PRIMARY KEY
job_id          UUID REFERENCES jobs(id)
approvers       TEXT[]          -- Slack user IDs
deadline        TIMESTAMPTZ
escalated       BOOLEAN DEFAULT FALSE
status          TEXT            -- PENDING / APPROVED / REJECTED / ESCALATED
approved_by     TEXT            -- Slack user ID
rejected_by     TEXT
rejection_reason TEXT
slack_message_ts TEXT           -- for message updates
created_at      TIMESTAMPTZ DEFAULT NOW()
```

### `audit_log`
```sql
id              UUID PRIMARY KEY
job_id          UUID REFERENCES jobs(id)
action          TEXT            -- RECEIVED / EXTRACTED / VENDOR_MATCHED / etc.
actor           TEXT            -- "system" or Slack user ID
details         JSONB           -- full context snapshot
created_at      TIMESTAMPTZ DEFAULT NOW()
```

---

## 6. Integration Map

| Service | Method | Auth | Key Actions |
|---|---|---|---|
| Gmail | REST API v1 + Pub/Sub | OAuth2 Service Account | Watch inbox, read emails, download attachments, send escalation emails |
| Google Drive | REST API v3 | OAuth2 Service Account | Upload, rename, move files, create folders |
| Google Sheets | REST API v4 | OAuth2 Service Account | Read Budget_Suivi_2025.xlsx |
| Claude | Anthropic Python SDK | API Key | Invoice extraction, GL classification |
| Pennylane | REST API | Bearer token (x8 entities) | POST invoice + PDF attachment |
| Slack | Bolt SDK (Socket Mode) | Bot token + App token | Post messages, handle interactions, post to channels |
| Notion | REST API v1 | Integration token | Create/update database rows |
| PostgreSQL | asyncpg / SQLAlchemy | Connection string | All state management |

---

## 7. Approval Rules Engine

```python
def get_approvers(invoice: InvoiceData, vendor: Vendor) -> ApprovalRequirement:

    # Rule 5: Unrecognized vendor → Marie mandatory
    if vendor is None:
        return ApprovalRequirement(
            approvers=[MARIE_SLACK_ID],
            deadline_hours=24,
            channel="#invoice-exceptions"
        )

    # Rule 4: Maintenance > 1000€ → Property Manager + Marie
    if vendor.default_gl == "615000" and invoice.total_ttc > 1000:
        pm = get_property_manager(invoice.cost_center)
        return ApprovalRequirement(
            approvers=[pm, MARIE_SLACK_ID],
            deadline_hours=48
        )

    # Rule 3: > 2000€ OR insurance/legal → Marie + Direction
    if invoice.total_ttc > 2000 or vendor.default_gl in ("616000", "622000"):
        return ApprovalRequirement(
            approvers=[MARIE_SLACK_ID, DIRECTION_SLACK_ID],
            deadline_hours=72
        )

    # Rule 2: 500€ to 2000€ → Marie
    if invoice.total_ttc >= 500:
        return ApprovalRequirement(
            approvers=[MARIE_SLACK_ID],
            deadline_hours=48
        )

    # Rule 1: < 500€ → Thomas
    return ApprovalRequirement(
        approvers=[THOMAS_SLACK_ID],
        deadline_hours=24
    )
```

---

## 8. Vendor Memory & Learning Loop

### Migration at Kickoff
1. Export `Fournisseurs_Codes_Marie.xlsx` from Marie's Google Drive
2. Parse and map columns → `vendors` table schema
3. Bulk insert ~45 records
4. Fill gaps (missing GL codes) interactively with Marie before go-live
5. Sync initial state to Notion `Fournisseurs` database

### Learning Loop
```
Human corrects GL / VAT / cost center in Slack modal
        │
        ▼
1. Update processed_invoices record
2. Update vendor record (default_gl, default_vat, cost_centers)
3. Set last_corrected_by = Slack user ID, last_corrected_at = NOW()
4. Log correction to audit_log with before/after snapshot
5. Sync updated vendor to Notion Fournisseurs
6. If same vendor corrected 3x for same field → Slack notification to Marie
   ("Vendor X default GL may be wrong — corrected 3 times this month")
```

---

## 9. Implementation Phases

### Phase 0 — Foundation (Week 1)
- [ ] Repo structure scaffolding (see Section 10)
- [ ] PostgreSQL setup on Render + schema migrations (Alembic)
- [ ] Environment config, secrets management (.env + Render env vars)
- [ ] Pydantic models for all domain objects
- [ ] Logging framework (structlog, JSON output)
- [ ] Basic FastAPI app with health endpoint
- [ ] Unit test skeleton (pytest)

### Phase 1 — Ingestion & Extraction (Week 2)
- [ ] Gmail API client — OAuth2, inbox watch, attachment download
- [ ] Google Drive client — upload to INBOX_RAW
- [ ] pdfplumber extraction + Tesseract OCR fallback
- [ ] Claude extraction agent with prompt engineering
- [ ] InvoiceData model validation
- [ ] Confidence scoring logic
- [ ] **Milestone**: feed 10 real sample invoices, verify extraction quality

### Phase 2 — Enrichment & Validation (Week 3)
- [ ] Vendor memory database + migration from Marie's Excel
- [ ] SIRET + fuzzy name matching (rapidfuzz)
- [ ] Cost center router (email header + PDF + vendor default)
- [ ] Duplicate detector
- [ ] VAT validator with edge case rules
- [ ] Math integrity check
- [ ] Budget checker via Google Sheets API
- [ ] **Milestone**: full enrichment pipeline on sample invoice set, exception routing correct

### Phase 3 — Approval Workflow (Week 4)
- [ ] Slack Bolt app setup (Socket Mode)
- [ ] Approval rules engine
- [ ] Block Kit message builder (invoice summary card with approve/reject/edit)
- [ ] Approval state machine (PostgreSQL-backed)
- [ ] APScheduler setup + escalation job
- [ ] Escalation: Slack #finance-alerts + email via Gmail API
- [ ] **Milestone**: full approve/reject cycle working end-to-end in Slack

### Phase 4 — Output Layer (Week 5)
- [ ] Pennylane API client (8 entity tokens)
- [ ] Invoice push + PDF attachment
- [ ] Google Drive filing (rename + move)
- [ ] Notion logger (Audit log + Factures en attente)
- [ ] Vendor Notion sync
- [ ] **Milestone**: approved invoice lands in Pennylane + Drive + Notion correctly

### Phase 5 — Edge Cases & Hardening (Week 6)
- [ ] Multi-line item invoices with GL split
- [ ] Mixed VAT invoices (food 5.5%/10%)
- [ ] Insurance VAT correction flag
- [ ] Metro/Transgourmet duplicate edge cases
- [ ] Forwarded email handling (property emails → AP inbox)
- [ ] Manual upload via INBOX_RAW polling
- [ ] Retry logic for all external API calls
- [ ] Dead letter queue for permanently failed jobs
- [ ] **Milestone**: all edge cases tested with real or realistic samples

### Phase 6 — Go-Live Prep (Week 7)
- [ ] Import complete vendor list (Marie's Excel + gap-fill session)
- [ ] Map all Slack user IDs for approvers and property managers
- [ ] Configure all Pennylane entity IDs and tokens
- [ ] Dry-run with 2 weeks of real historical invoices (compare to what was manually entered)
- [ ] Thomas and Marie walkthrough of Slack approval flow
- [ ] Monitoring dashboard (simple Slack daily digest + Render logs)
- [ ] **Milestone**: parallel run — agent processes + humans verify, zero discrepancies

### Phase 7 — Handover (Week 8)
- [ ] Runbook documentation (ops guide for Thomas)
- [ ] Vendor memory admin guide (how to add/correct vendors)
- [ ] Known edge case catalog
- [ ] Monitoring and alert playbook
- [ ] First solo run without parallel verification

---

## 10. File & Folder Structure

```
Invoice-to-Accounting-Agent/
│
├── agent/
│   ├── __init__.py
│   ├── claude_agent.py          # LLM extraction + prompt
│   ├── extractor.py             # pdfplumber + OCR pipeline
│   ├── vendor_memory.py         # DB lookup, fuzzy match, learning loop
│   ├── cost_center_router.py    # Email header + PDF content routing
│   ├── duplicate_detector.py
│   ├── vat_validator.py
│   ├── budget_checker.py        # Google Sheets budget read
│   ├── approval_engine.py       # Rules engine + Slack message builder
│   ├── scheduler.py             # APScheduler jobs
│   │
│   ├── listeners/
│   │   ├── gmail_listener.py    # Gmail watch + attachment download
│   │   └── drive_listener.py    # INBOX_RAW polling for manual uploads
│   │
│   ├── clients/
│   │   ├── gmail_client.py
│   │   ├── drive_client.py
│   │   ├── sheets_client.py
│   │   ├── pennylane_client.py
│   │   ├── slack_bot.py         # Slack Bolt app + interaction handlers
│   │   └── notion_client.py
│   │
│   └── models/
│       ├── invoice.py           # InvoiceData, LineItem, VATLine Pydantic models
│       ├── vendor.py            # Vendor model
│       ├── job.py               # Job state model
│       └── approval.py         # ApprovalRequirement model
│
├── api/
│   ├── main.py                  # FastAPI app, lifespan, health endpoint
│   └── routes/
│       ├── webhooks.py          # Gmail Pub/Sub push webhook
│       └── admin.py             # Manual trigger endpoints
│
├── db/
│   ├── connection.py            # asyncpg pool setup
│   ├── migrations/              # Alembic migrations
│   └── queries/
│       ├── vendors.py
│       ├── jobs.py
│       └── approvals.py
│
├── prompts/
│   ├── extraction_fr.md         # Claude system prompt — French invoices
│   ├── extraction_en.md         # Claude system prompt — English invoices
│   └── gl_classification.md    # GL account classification instructions
│
├── scripts/
│   ├── import_vendor_excel.py   # One-time migration of Marie's Excel
│   └── backfill_invoices.py     # Dry-run on historical invoices
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│       └── sample_invoices/     # Anonymized test PDFs
│
├── .env.example
├── requirements.txt
├── alembic.ini
├── render.yaml                  # Render deployment config
├── PLAN.md                      # This file
└── README.md
```

---

## 11. Environment & Secrets

```bash
# Anthropic
ANTHROPIC_API_KEY=

# Google (Service Account JSON path or inline)
GOOGLE_SERVICE_ACCOUNT_JSON=
GMAIL_AP_INBOX=                  # shared AP inbox address
GMAIL_MARIE_EMAIL=
GMAIL_THOMAS_EMAIL=
GMAIL_GM_EMAIL=
GOOGLE_DRIVE_ROOT_FOLDER_ID=
GOOGLE_BUDGET_SHEET_ID=

# Pennylane (one per entity)
PENNYLANE_TOKEN_CC01=
PENNYLANE_TOKEN_CC02=
PENNYLANE_TOKEN_CC03=
PENNYLANE_TOKEN_CC04=
PENNYLANE_TOKEN_CC05=
PENNYLANE_TOKEN_CC06=
PENNYLANE_TOKEN_CC07=
PENNYLANE_TOKEN_CC08=
PENNYLANE_BASE_URL=https://app.pennylane.com/api/v1

# Slack
SLACK_BOT_TOKEN=
SLACK_APP_TOKEN=                 # for Socket Mode
SLACK_CHANNEL_INVOICES=         # #invoices-to-approve channel ID
SLACK_CHANNEL_EXCEPTIONS=       # #invoice-exceptions channel ID
SLACK_CHANNEL_ALERTS=           # #finance-alerts channel ID
SLACK_CHANNEL_FINANCE_OPS=      # #finance-ops channel ID

# Slack User IDs (provided on hiring)
SLACK_USER_MARIE=
SLACK_USER_THOMAS=
SLACK_USER_DIRECTION=
SLACK_USER_PM_CC01=
SLACK_USER_PM_CC02=
SLACK_USER_PM_CC03=
SLACK_USER_PM_CC04=
SLACK_USER_PM_CC05=
SLACK_USER_PM_CC06=

# Notion
NOTION_TOKEN=
NOTION_DB_VENDORS=              # Fournisseurs database ID
NOTION_DB_PENDING=              # Factures en attente database ID
NOTION_DB_AUDIT=                # Journal d'audit database ID

# Database
DATABASE_URL=                   # PostgreSQL connection string (Render Postgres)

# App
APP_ENV=production              # development / production
LOG_LEVEL=INFO
```

---

## 12. Open Questions Before Build

These must be resolved before or during Phase 0:

| # | Question | Owner | Impact |
|---|---|---|---|
| 1 | What is the exact shared AP inbox address? | Marie | Gmail Listener config |
| 2 | Can we create a Google Service Account with Drive + Gmail + Sheets access? | Client IT / Marie | All Google integrations |
| 3 | What are the 8 Pennylane entity/company IDs, and are API tokens already created? | Marie | Phase 4 blocked without this |
| 4 | What are the Slack user IDs for all approvers and property managers? | Thomas | Approval routing |
| 5 | Does Pennylane's API support multipart invoice creation (fields + PDF)? | Pennylane docs | Output layer design |
| 6 | Is Budget_Suivi_2025.xlsx a Google Sheet or a true Excel file on Drive? | Thomas | Sheets vs Drive API path |
| 7 | Can we get access to Marie's Fournisseurs_Codes_Marie.xlsx at kickoff? | Marie | Phase 2 vendor migration |
| 8 | What Notion databases already exist, and can we create new ones? | Thomas | Notion integration |
| 9 | Are there any invoices that arrive as email body (no PDF)? | Marie | Extractor scope |
| 10 | Do property managers have Slack and are they active users? | Thomas | Approval flow reliability |
