# LPSC Track

Python tools for monitoring [Louisiana Public Service Commission (LPSC)](https://lpsc.louisiana.gov/) regulatory activity. The LPSC publishes official bulletins every two weeks listing docket activity across Louisiana utilities — dense PDFs covering transportation, telecom, water, gas, and electric. These tools help you stay on top of what matters.

This repo contains two tools:

- **lpsc_monitor** — Single-user bulletin monitor with AI-powered document summaries
- **lpsc_alerts** — Multi-user alert system for tracking keywords and specific dockets

## Quick Start

### Prerequisites

- Python 3.9+
- A Gmail account with [2FA enabled](https://myaccount.google.com/security) (for email delivery)

### Installation

```bash
# Clone the repo
git clone https://github.com/mattxrex/lpsc-track.git
cd lpsc-track

# Create and activate virtual environment
python3 -m venv lpsc_monitor/venv
source lpsc_monitor/venv/bin/activate

# Install dependencies
pip install -r lpsc_monitor/requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your email settings
```

### Configuration

Edit the `.env` file with your credentials:

```
EMAIL_SENDER=your.email@gmail.com
EMAIL_APP_PASSWORD=your-gmail-app-password
```

For the Gmail App Password: enable 2FA on your Gmail account, then generate an App Password at https://myaccount.google.com/apppasswords.

`lpsc_monitor` also requires an Anthropic API key for document summarization:

```
ANTHROPIC_API_KEY=your-api-key-here
EMAIL_RECIPIENTS=recipient1@example.com,recipient2@example.com
```

---

## lpsc_alerts — Multi-User Keyword & Docket Alerts

A lightweight alert system that lets you set up multiple users, each with their own keywords and tracked dockets. When new regulatory activity matches, each user gets a concise email with links to the relevant documents on the LPSC portal.

No AI summaries — just parsing, matching, and links. Ideal for sharing tailored regulatory alerts with colleagues who each care about different things.

### How It Works

The tool monitors for relevant activity through two paths:

1. **Keyword discovery** — When a new LPSC bulletin is published, the tool parses it and checks each docket entry against each user's keywords. This discovers things users didn't know to look for. For example, a user tracking "Entergy" will be alerted whenever Entergy appears in a new bulletin docket, even if they weren't watching that specific docket number.

2. **Direct docket tracking** — Users can specify docket numbers (e.g., "U-36625") to watch. The tool polls the LPSC portal for new documents filed on those dockets, regardless of whether a bulletin has been published. This catches filings between bulletins.

Both paths feed into **one email per user** — no duplicate emails, no noise.

### Managing Users

All user management is done through the command line. Always activate the virtual environment first:

```bash
source lpsc_monitor/venv/bin/activate
cd lpsc_alerts
```

**Add a user** with keywords and/or tracked dockets:

```bash
# Track by keywords — get alerts when these terms appear in new bulletins
python main.py add-user alice@example.com --keywords "Entergy,solar,rate case"

# Track specific dockets — get alerts when new documents are filed
python main.py add-user bob@example.com --dockets "U-36625,U-37800"

# Both keywords and dockets, plus exclusions to filter out noise
python main.py add-user carol@example.com \
    --keywords "DEMCO,Cleco,wind,transmission" \
    --exclude "gas,water,telephone" \
    --dockets "U-37584"
```

Keywords are matched case-insensitively with word boundaries. For example, "solar" matches "Solar energy facility" but not "insolar". Common keyword choices:

- **Company names**: Entergy, Cleco, SWEPCO, DEMCO, SLEMCO
- **Energy terms**: solar, wind, transmission, generation, battery
- **Regulatory terms**: rate case, tariff, IRP, integrated resource plan
- **Exclusions**: gas, water, telephone, VoIP (filters out unrelated dockets)

**Update a user** — add or remove keywords and dockets without replacing everything:

```bash
# Add new keywords
python main.py update-user alice@example.com --add-keywords "wind,battery"

# Remove a keyword
python main.py update-user alice@example.com --remove-keywords "solar"

# Add exclusions
python main.py update-user alice@example.com --add-exclude "gas,water"

# Start tracking a new docket
python main.py update-user alice@example.com --add-dockets "U-37584"

# Stop tracking a docket
python main.py update-user alice@example.com --remove-dockets "U-36625"
```

**List all users** and their current settings:

```bash
python main.py list-users
```

**Remove a user** and all their data:

```bash
python main.py remove-user alice@example.com
```

### Running Checks

```bash
# One-shot: check for new bulletins and docket filings, send alerts
python main.py check

# Continuous: run check every 24 hours (Ctrl+C to stop)
python main.py monitor

# Test that email delivery works
python main.py test-alert your.email@example.com

# Automatic scheduling (macOS only) — runs check daily at 6 AM
python main.py setup-schedule
```

The `check` command runs both monitoring paths, groups all alerts by user, sends one email per user, and records what was sent so the same item is never alerted twice.

The `setup-schedule` command installs a macOS launchd job that runs `check` automatically every day at 6 AM. Unlike lpsc_monitor (which dynamically schedules based on the next bulletin date), lpsc_alerts uses a fixed daily schedule because it also monitors tracked dockets for new filings between bulletins.

### Architecture

```
lpsc_alerts/
├── main.py              # CLI entry point
├── config.py            # Portal URLs, paths, email settings
├── database.py          # SQLite: users, tracked dockets, sent alerts, bulletins
├── user_manager.py      # User add/remove/update/list
├── keyword_matcher.py   # Include/exclude keyword matching
├── bulletin_monitor.py  # Path 1: RSS → parse bulletins → match user keywords
├── docket_monitor.py    # Path 2: Poll portal API for new docket documents
├── portal_api.py        # LPSC Document Search API wrapper
├── alert_generator.py   # HTML email builder
├── email_sender.py      # Gmail SMTP delivery
├── bulletin_parser.py   # PDF parsing (shared with lpsc_monitor)
├── bulletin_downloader.py # PDF download (shared with lpsc_monitor)
├── schedule.py          # macOS launchd scheduling (daily at 6 AM)
└── data/
    └── lpsc_alerts.db   # SQLite database (created automatically, gitignored)
```

---

## lpsc_monitor — Single-User Bulletin Monitor with AI Summaries

A comprehensive monitoring tool for a single user (or a fixed recipient list). Goes deeper than lpsc_alerts: it downloads supporting documents for each relevant docket and summarizes them using Claude AI.

### What It Does

1. **Detects** new bulletins via the LPSC RSS feed
2. **Downloads** the bulletin PDF from the LPSC portal
3. **Parses** docket entries and assigns them to bulletin subparts (sections A through J)
4. **Scores** each docket against configurable keyword lists (electric utilities, energy terms, company names) and filters out non-electric topics
5. **Fetches** supporting documents from the LPSC portal for relevant dockets
6. **Summarizes** each document using Claude AI (Haiku) with structured output
7. **Emails** an HTML report organized by bulletin section with document summaries and portal links
8. **Schedules** the next check based on the bulletin's published next-mailing date (macOS launchd)

### Usage

```bash
source lpsc_monitor/venv/bin/activate

# Full automated pipeline
python lpsc_monitor/main.py check

# Individual steps
python lpsc_monitor/main.py fetch-docs 1368
python lpsc_monitor/main.py summarize 1368
python lpsc_monitor/main.py email-report 1368
python lpsc_monitor/main.py cleanup 1368

# Other commands
python lpsc_monitor/main.py report 1368        # Plain-text report
python lpsc_monitor/main.py stats              # Database statistics
python lpsc_monitor/main.py test <pdf_path>    # Test-parse a PDF

# Automatic scheduling (macOS only)
python lpsc_monitor/main.py setup-schedule
```

### Relevance Scoring

Dockets are scored against three keyword lists defined in `config.py`:

| Category | Points | Examples |
|----------|--------|---------|
| High priority | +10 | Entergy, Cleco, SWEPCO, solar, transmission, rate case |
| Medium priority | +3 | utility, energy, capacity, customer, wholesale |
| Exclusion | -15 | VoIP, telephone, water utility, gas pipeline |

A docket is marked **relevant** if its score is 5 or higher. Keywords, scores, and the threshold are all configurable in `lpsc_monitor/config.py`.

---

## Dependencies

All listed in `lpsc_monitor/requirements.txt`:

- **pdfplumber** — PDF text extraction
- **requests** — HTTP downloads
- **beautifulsoup4** — HTML parsing for portal scraping
- **feedparser** — RSS feed parsing
- **python-dotenv** — Environment variable loading
- **anthropic** — Claude API (lpsc_monitor only)

## License

This project is for personal use. No license is currently applied.
