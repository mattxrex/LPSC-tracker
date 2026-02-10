"""
Configuration for LPSC Alerts — Multi-User Docket Monitoring

Loads email credentials from .env and defines portal URLs and paths.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (one level up from this file)
load_dotenv(Path(__file__).parent.parent / ".env")

# =============================================================================
# PATHS
# =============================================================================

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
BULLETINS_DIR = DATA_DIR / "bulletins"
DATABASE_PATH = DATA_DIR / "lpsc_alerts.db"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
BULLETINS_DIR.mkdir(exist_ok=True)

# =============================================================================
# LPSC PORTAL SETTINGS
# =============================================================================

LPSC_BASE_URL = "https://lpscpubvalence.lpsc.louisiana.gov"
LPSC_PORTAL_URL = f"{LPSC_BASE_URL}/portal"
LPSC_RSS_URL = f"{LPSC_PORTAL_URL}/PSC/GetRssView?type=Recent%20Bulletins"
DOCUMENT_SEARCH_URL = f"{LPSC_PORTAL_URL}/PSC/DocumentSearch"

# How far back (in days) to look for documents on tracked dockets
DOCKET_DOCUMENT_LOOKBACK_DAYS = 30

# How often to check in monitor mode (seconds) — 24 hours
MONITOR_INTERVAL = 86400

# =============================================================================
# BULLETIN PARSING SETTINGS (used by copied bulletin_parser.py)
# =============================================================================

DOCKET_PATTERN = r"([URISX])-(\d+)"
PART_II_MARKERS = ["PART II", "Part II", "UTILITIES", "UTILITY SECTION"]
RELEVANT_DOCKET_TYPES = ["U", "R", "I", "S", "X", "SPECIAL", "GENERAL"]

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
# EMAIL SETTINGS
# =============================================================================

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")

# =============================================================================
# LOGGING
# =============================================================================

DEBUG = True

def log(message):
    """Simple logging function for debugging."""
    if DEBUG:
        print(f"[DEBUG] {message}")
