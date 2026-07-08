"""
Configuration settings for LPSC Bulletin Monitor

This file contains all the settings, keywords, and constants used
throughout the application. Edit this file to customize filtering behavior.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file (contains ANTHROPIC_API_KEY)
load_dotenv(Path(__file__).parent.parent / ".env")

# =============================================================================
# PATHS
# =============================================================================

# Base directory is where this config file lives
BASE_DIR = Path(__file__).parent

# Data storage locations
DATA_DIR = BASE_DIR / "data"
BULLETINS_DIR = DATA_DIR / "bulletins"
DOCUMENTS_DIR = DATA_DIR / "documents"
DATABASE_PATH = DATA_DIR / "lpsc_monitor.db"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
BULLETINS_DIR.mkdir(exist_ok=True)
DOCUMENTS_DIR.mkdir(exist_ok=True)

# =============================================================================
# LPSC PORTAL SETTINGS
# =============================================================================

LPSC_BASE_URL = "https://lpscpubvalence.lpsc.louisiana.gov"
LPSC_PORTAL_URL = f"{LPSC_BASE_URL}/portal"

# RSS feed URL - returns the most recent bulletins
LPSC_RSS_URL = f"{LPSC_PORTAL_URL}/PSC/GetRssView?type=Recent%20Bulletins"

# Document search API
DOCUMENT_SEARCH_URL = f"{LPSC_PORTAL_URL}/PSC/DocumentSearch"

# How far back (in days) from a bulletin's date to look for new docket documents
# Bulletins come out roughly every 2 weeks, so 16 days gives a comfortable margin
DOCUMENT_DATE_WINDOW_DAYS = 16

# How often to check for new bulletins in monitor mode (seconds)
# Default: 86400 = 24 hours
MONITOR_INTERVAL = 86400

# =============================================================================
# DOCKET TYPES
# =============================================================================

# Dictionary of docket prefixes and their meanings
# We're primarily interested in U-, R-, and I- dockets
DOCKET_TYPES = {
    "U": "Utility matters (electric, gas, water)",
    "R": "Rulemakings",
    "I": "Integrated Resource Plans (IRPs)",
    "S": "Service/telecom",
    "X": "Repository/miscellaneous",
    "T": "Transportation (skip these)",
    "SPECIAL": "Special Orders (Commission actions)",
    "GENERAL": "General Orders (rulemaking conclusions)",
}

# Docket types we want to track (exclude Transportation)
RELEVANT_DOCKET_TYPES = ["U", "R", "I", "S", "X", "SPECIAL", "GENERAL"]

# =============================================================================
# KEYWORDS FOR FILTERING
# =============================================================================

# High-priority keywords - if found, docket is definitely relevant
# These are matched case-insensitively
HIGH_PRIORITY_KEYWORDS = [
    # Energy types
    "electric",
    "electricity",
    "solar",
    "wind",
    "renewable",
    "battery",
    "storage",
    "generation",
    "transmission",
    "distribution",
    "grid",

    # Regulatory terms
    "IRP",
    "integrated resource plan",
    "rate case",
    "rate increase",
    "rate decrease",
    "rate schedule",
    "tariff",
    "rider",
    "fuel adjustment",

    # Investor-Owned Utilities (IOUs)
    "Entergy",
    "Cleco",
    "SWEPCO",
    "Southwestern Electric Power",

    # Electric Cooperatives
    "DEMCO",
    "Dixie Electric",
    "SLECA",
    "South Louisiana Electric Cooperative",
    "Jeff Davis Electric",
    "Beauregard Electric",
    "1803 Electric",
    "SLEMCO",
    "Southwest Louisiana Electric",
    "Pointe Coupee Electric",
    "Washington-St. Tammany Electric",
    "Claiborne Electric",
    "Valley Electric",
    "Northeast Louisiana Power",
    "NOLP",

    # Data center / fiber (telecom of interest)
    "data center",
    "fiber",
]

# Medium-priority keywords - relevant but less critical
MEDIUM_PRIORITY_KEYWORDS = [
    "utility",
    "energy",
    "capacity",
    "demand",
    "load",
    "megawatt",
    "MW",
    "kWh",
    "kilowatt",
    "voltage",
    "substation",
    "interconnection",
    "net metering",
    "cogeneration",
    "wholesale",
    "retail",
    "customer",
    "residential",
    "commercial",
    "industrial",
]

# Keywords that indicate the docket is NOT about electric utilities
# (helps filter out gas, water, and non-fiber telecom matters)
EXCLUSION_KEYWORDS = [
    # Gas and water
    "pipeline",
    "water utility",
    "sewer",
    "wastewater",

    # Non-fiber telecom (not interested unless data center/fiber related)
    "VoIP",
    "Voice over Internet Protocol",
    "telephone",
    "wireless",
    "cellular",
    "cable television",
]

# =============================================================================
# SCORING SETTINGS
# =============================================================================

# Points for relevance scoring
HIGH_PRIORITY_SCORE = 10
MEDIUM_PRIORITY_SCORE = 3
EXCLUSION_PENALTY = -15

# Minimum score to be considered "relevant"
RELEVANCE_THRESHOLD = 5

# =============================================================================
# USER-ADDED CUSTOM KEYWORDS
# =============================================================================
# Keywords added via `python main.py add-keyword` are stored in a separate JSON
# file (kept out of this source file on purpose) and merged into the lists above
# at startup. This keeps personal additions separate from the built-in defaults.

import json as _json

CUSTOM_KEYWORDS_FILE = DATA_DIR / "custom_keywords.json"

# Maps a tier name to the keyword list it feeds into and the points it carries.
KEYWORD_TIERS = {
    "high": (HIGH_PRIORITY_KEYWORDS, HIGH_PRIORITY_SCORE),
    "medium": (MEDIUM_PRIORITY_KEYWORDS, MEDIUM_PRIORITY_SCORE),
    "exclude": (EXCLUSION_KEYWORDS, EXCLUSION_PENALTY),
}


def _load_custom_keywords():
    """Return {'high': [...], 'medium': [...], 'exclude': [...]} from the JSON file."""
    empty = {tier: [] for tier in KEYWORD_TIERS}
    try:
        with open(CUSTOM_KEYWORDS_FILE) as f:
            data = _json.load(f)
    except (FileNotFoundError, ValueError):
        return empty
    return {tier: list(data.get(tier, [])) for tier in KEYWORD_TIERS}


# The user's additions, kept separate so we can show which keywords are custom.
CUSTOM_KEYWORDS = _load_custom_keywords()

# Fold the custom keywords into the built-in lists (case-insensitive de-dupe),
# so the scoring in filter.py picks them up with no changes needed there.
for _tier, (_target_list, _pts) in KEYWORD_TIERS.items():
    _existing = {k.lower() for k in _target_list}
    for _term in CUSTOM_KEYWORDS[_tier]:
        if _term.lower() not in _existing:
            _target_list.append(_term)
            _existing.add(_term.lower())

# =============================================================================
# BULLETIN SUBPART SECTIONS (Part II - Utilities)
# =============================================================================

# Maps the letter prefix to the display name for each subpart of Part II.
# These appear in bulletin PDFs as headers like "A. RATE APPLICATIONS"
SUBPART_SECTIONS = {
    "A": "Rate Applications",
    "B": "Citations",
    "C": "Requests for Authority",
    "D": "Letters of Non-Opposition",
    "E": "Adjudications",
    "F": "Rulemakings",
    "G": "Tariff Filings",
    "H": "Section 301 M. Notice and Interconnection Agreement Filings",
    "I": "Miscellaneous",
    "J": "Orders",
}

# =============================================================================
# PDF PARSING SETTINGS
# =============================================================================

# Section markers in bulletin PDFs
PART_II_MARKERS = [
    "PART II",
    "Part II",
    "UTILITIES",
    "UTILITY SECTION",
]

# Regex pattern for docket numbers (e.g., U-37800, R-12345, I-99999)
# This pattern matches: letter(s) + hyphen + numbers
DOCKET_PATTERN = r"([URISX])-(\d+)"

# =============================================================================
# CLAUDE API SETTINGS
# =============================================================================

# Model to use for document summarization (Haiku = fast and cheap)
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

# Max output tokens for each summary response
CLAUDE_MAX_TOKENS = 1024

# Seconds to wait between API calls (avoids rate limits)
CLAUDE_DELAY_BETWEEN_CALLS = 2.0

# Heuristic: ~20,000 tokens per MB of PDF (for estimating if chunking is needed)
CLAUDE_TOKENS_PER_MB = 20000

# If estimated token count exceeds this, use text-chunking fallback instead
# of sending the whole PDF. Haiku supports 200k context, but we leave margin.
CLAUDE_MAX_INPUT_TOKENS = 150000

# For chunking fallback: max tokens per chunk and chars-per-token estimate
CLAUDE_CHUNK_MAX_TOKENS = 100000
CLAUDE_CHARS_PER_TOKEN = 4

# =============================================================================
# EMAIL SETTINGS
# =============================================================================

# Gmail SMTP settings for sending email reports
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# Sender email address (your Gmail)
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")

# Gmail App Password (stored in .env file for security)
# To set up: Enable 2FA on Gmail, then generate an App Password at
# https://myaccount.google.com/apppasswords
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")

# Recipients — comma-separated list of email addresses
# Set via .env or override here
EMAIL_RECIPIENTS = [
    addr.strip()
    for addr in os.getenv("EMAIL_RECIPIENTS", "").split(",")
    if addr.strip()
]

# Admin email — receives system alerts (e.g., API credit exhaustion)
# Falls back to EMAIL_SENDER if not set
EMAIL_ADMIN = os.getenv("EMAIL_ADMIN", "") or EMAIL_SENDER

# =============================================================================
# LOGGING
# =============================================================================

# Set to True for verbose output during development
DEBUG = True

def log(message):
    """Simple logging function for debugging."""
    if DEBUG:
        print(f"[DEBUG] {message}")
