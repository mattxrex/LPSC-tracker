# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LPSC Bulletin Monitor - A Python tool to monitor Louisiana Public Service Commission (LPSC) Official Bulletins for electric utility-related regulatory content.

## Commands

```bash
# Activate virtual environment (required before running)
source lpsc_monitor/venv/bin/activate

# Check RSS feed for new bulletins and process any found (one-shot)
python lpsc_monitor/main.py check

# Continuously monitor for new bulletins (checks every 24 hours, Ctrl+C to stop)
python lpsc_monitor/main.py monitor

# Process a specific bulletin by URL (manual)
python lpsc_monitor/main.py process '<PDF_URL>' <BULLETIN_NUMBER>

# Generate report of relevant dockets
python lpsc_monitor/main.py report [BULLETIN_NUMBER]

# Show database statistics
python lpsc_monitor/main.py stats

# Test parsing a local PDF without saving
python lpsc_monitor/main.py test <PDF_PATH>

# Download new docket documents for a bulletin's relevant dockets
python lpsc_monitor/main.py fetch-docs [BULLETIN_NUMBER]

# Summarize downloaded documents using Claude AI (Haiku)
python lpsc_monitor/main.py summarize [BULLETIN_NUMBER]

# Generate HTML email report and send it
python lpsc_monitor/main.py email-report [BULLETIN_NUMBER]

# Delete downloaded PDFs after processing (DB retains summaries)
python lpsc_monitor/main.py cleanup [BULLETIN_NUMBER]

# Install macOS launchd job for automatic scheduled checks
python lpsc_monitor/main.py setup-schedule
```

## Architecture

```
lpsc_monitor/
├── main.py              # CLI orchestrator - all commands, full pipeline automation
├── config.py            # Keywords, scoring, paths, email settings, subpart mapping
├── rss_monitor.py       # RSS feed fetching, PDF URL extraction, new bulletin detection
├── bulletin_parser.py   # PDF text extraction, subpart detection, regex parsing for docket entries
├── filter.py            # Keyword matching, relevance scoring
├── database.py          # SQLite operations (bulletins, dockets, documents tables + migrations)
├── bulletin_downloader.py  # Download PDFs from LPSC portal
├── document_fetcher.py  # Download docket documents from LPSC portal by date window
├── document_summarizer.py # Claude API summarization of docket documents
├── email_report.py      # HTML email report generation organized by subparts A-J
├── email_sender.py      # Gmail SMTP email delivery
├── storage.py           # PDF cleanup after processing
├── schedule_next.py     # macOS launchd schedule management
└── data/
    ├── bulletins/       # Downloaded bulletin PDFs (cleaned up after processing)
    ├── documents/       # Downloaded docket documents (cleaned up after processing)
    └── lpsc_monitor.db  # SQLite database
```

**Full automated pipeline (`check` command):** RSS feed → find new bulletins → download PDF → extract text → detect subparts (A-J) → parse docket entries → score → store → fetch docket documents → summarize with Claude → clean up PDFs → send HTML email report → update launchd schedule for next bulletin date

**Manual flow:** PDF URL → download → extract text → find Part II section → parse docket entries (DOCKET NO., ORDER NO., GENERAL ORDER, SPECIAL ORDER) → assign subparts → score against keywords → store in SQLite

**Document fetch flow:** Bulletin → get relevant dockets → for each docket, search portal for docs filed in date window → download new PDFs → store in documents table

**Summarize flow:** Bulletin → find unsummarized documents → send each PDF to Claude Haiku → store structured summary in database (large PDFs use text-chunking fallback)

## LPSC Portal Access

- **RSS Feed** (latest bulletin only): `https://lpscpubvalence.lpsc.louisiana.gov/portal/PSC/GetRssView?type=Recent%20Bulletins`
- **Document Search API**: `POST /portal/PSC/DocumentSearch` — Kendo ASP.NET MVC format, requires `X-Requested-With: XMLHttpRequest` header and session cookie
- **Document Details**: `/portal/PSC/DocumentDetails?documentId=XXXXX` → contains PDF link
- **PDF Download**: `/portal/PSC/ViewFile?fileId=XXXXX`

The bulletin list on the portal loads dynamically via JavaScript. DocumentIds are not sequential.

## Current Status

**Working:**
- RSS-based automatic new bulletin detection (`check` and `monitor` commands)
- Download and parse bulletin PDFs (tested on 7 bulletins, 52 dockets)
- Extract all entry types: DOCKET NO., ORDER NO., GENERAL ORDER, SPECIAL ORDER
- Subpart detection (A through J) — assigns each docket to its bulletin section
- Next bulletin date extraction from PDF text
- Keyword-based relevance scoring with exclusions (VoIP, water, gas filtered out)
- SQLite storage and reporting (with automatic schema migrations)
- All Louisiana electric utilities in keyword list
- Download docket documents filed within a bulletin's date window (`fetch-docs` command)
- Claude API document summarization with structured summaries (`summarize` command)
- HTML email reports organized by subpart, with document summaries and portal links
- Gmail SMTP email delivery (`email-report` command)
- PDF storage cleanup after processing (`cleanup` command)
- Full pipeline automation: `check` runs fetch → summarize → cleanup → email → schedule
- macOS launchd scheduling based on next bulletin date (`setup-schedule` command)

**Setup needed:**
- Email: Enable 2FA on Gmail, create App Password at https://myaccount.google.com/apppasswords
- Set EMAIL_SENDER, EMAIL_APP_PASSWORD, EMAIL_RECIPIENTS in `.env`
- Scheduling: Run `python main.py setup-schedule` once to install the launchd job
- Consider: raise `CLAUDE_MAX_INPUT_TOKENS` to 180k if chunking quality is poor on future large docs

## Key Configuration (config.py)

- `HIGH_PRIORITY_KEYWORDS`: +10 points (utilities, energy terms, company names)
- `MEDIUM_PRIORITY_KEYWORDS`: +3 points (utility, capacity, customer, etc.)
- `EXCLUSION_KEYWORDS`: -15 points (VoIP, telephone, water utility, gas pipeline)
- `RELEVANCE_THRESHOLD`: 5 points minimum to be marked relevant
- `DEBUG = True`: Set to False for cleaner output
