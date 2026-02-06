# LPSC Bulletin Monitor

A Python tool that monitors [Louisiana Public Service Commission (LPSC)](https://lpsc.louisiana.gov/) Official Bulletins for electric utility regulatory content. It automatically detects new bulletins, parses docket entries, scores them for relevance, fetches supporting documents, summarizes them with AI, and delivers an HTML email report.

## What It Does

The LPSC publishes official bulletins every two weeks listing regulatory docket activity across Louisiana utilities. These bulletins are dense PDFs covering transportation, telecom, water, gas, and electric — but only a fraction is relevant to electric utility stakeholders.

This tool automates the monitoring process:

1. **Detects** new bulletins via the LPSC RSS feed
2. **Downloads** the bulletin PDF from the LPSC portal
3. **Parses** docket entries and assigns them to bulletin subparts (sections A through J)
4. **Scores** each docket against configurable keyword lists (electric utilities, energy terms, company names) and filters out non-electric topics (gas, water, telecom)
5. **Fetches** supporting documents from the LPSC portal for relevant dockets
6. **Summarizes** each document using Claude AI (Haiku) with structured output (Action, Parties, Key Details, Status)
7. **Emails** an HTML report organized by bulletin section with document summaries and portal links
8. **Cleans up** downloaded PDFs after processing to minimize disk usage
9. **Schedules** the next check based on the bulletin's published next-mailing date (macOS launchd)

## Quick Start

### Prerequisites

- Python 3.9+
- macOS (for launchd scheduling; everything else is cross-platform)
- A Gmail account with [2FA enabled](https://myaccount.google.com/security) (for email reports)
- An [Anthropic API key](https://console.anthropic.com/) (for document summarization)

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
# Edit .env with your API key and email settings
```

### Configuration

Edit the `.env` file with your credentials:

```
ANTHROPIC_API_KEY=your-api-key-here
EMAIL_SENDER=your.email@gmail.com
EMAIL_APP_PASSWORD=your-gmail-app-password
EMAIL_RECIPIENTS=recipient1@example.com,recipient2@example.com
```

For the Gmail App Password: enable 2FA on your Gmail account, then generate an App Password at https://myaccount.google.com/apppasswords.

### Usage

```bash
# Activate the virtual environment first
source lpsc_monitor/venv/bin/activate

# Check for new bulletins and run the full pipeline
# (parse, fetch docs, summarize, email report, clean up)
python lpsc_monitor/main.py check

# Same as above but skip sending the email (good for testing)
python lpsc_monitor/main.py check --no-email

# Run individual pipeline steps manually
python lpsc_monitor/main.py fetch-docs 1368
python lpsc_monitor/main.py summarize 1368
python lpsc_monitor/main.py email-report 1368
python lpsc_monitor/main.py cleanup 1368

# Other commands
python lpsc_monitor/main.py report 1368        # Plain-text report
python lpsc_monitor/main.py stats              # Database statistics
python lpsc_monitor/main.py test <pdf_path>    # Test-parse a PDF without saving

# Set up automatic scheduling (macOS only)
python lpsc_monitor/main.py setup-schedule
```

## Architecture

```
lpsc_monitor/
├── main.py                # CLI entry point — all commands, pipeline automation
├── config.py              # Keywords, scoring, paths, email settings, subpart mapping
├── rss_monitor.py         # RSS feed monitoring and new bulletin detection
├── bulletin_parser.py     # PDF text extraction, subpart detection, docket parsing
├── bulletin_downloader.py # PDF download from LPSC portal
├── filter.py              # Keyword matching and relevance scoring
├── database.py            # SQLite operations with automatic schema migrations
├── document_fetcher.py    # Docket document download from LPSC portal
├── document_summarizer.py # Claude AI document summarization
├── email_report.py        # HTML email report generation (organized by subpart)
├── email_sender.py        # Gmail SMTP email delivery
├── storage.py             # PDF cleanup after processing
├── schedule_next.py       # macOS launchd schedule management
└── data/
    └── lpsc_monitor.db    # SQLite database (created automatically)
```

## Relevance Scoring

Dockets are scored against three keyword lists defined in `config.py`:

| Category | Points | Examples |
|----------|--------|---------|
| High priority | +10 | Entergy, Cleco, SWEPCO, solar, transmission, rate case |
| Medium priority | +3 | utility, energy, capacity, customer, wholesale |
| Exclusion | -15 | VoIP, telephone, water utility, gas pipeline |

A docket is marked **relevant** if its score is 5 or higher. Keywords, scores, and the threshold are all configurable.

## Dependencies

All listed in `requirements.txt`:

- **pdfplumber** — PDF text extraction
- **requests** — HTTP downloads
- **beautifulsoup4** — HTML parsing for portal scraping
- **anthropic** — Claude API for document summarization
- **feedparser** — RSS feed parsing
- **python-dotenv** — Environment variable loading

Email sending and launchd scheduling use Python standard library only (`smtplib`, `email.mime`, `plistlib`).

## License

This project is for personal use. No license is currently applied.
