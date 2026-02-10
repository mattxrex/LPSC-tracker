"""
LPSC Portal API Wrapper

Handles session management and document search for the LPSC portal.
Extracted from lpsc_monitor/document_fetcher.py.

The Document Search API requires:
1. An ASP.NET session cookie (obtained by visiting the portal first)
2. The X-Requested-With: XMLHttpRequest header on POST requests
"""

import requests
from datetime import datetime
from typing import List, Dict

from config import LPSC_PORTAL_URL, LPSC_BASE_URL, DOCUMENT_SEARCH_URL, log


def create_session() -> requests.Session:
    """
    Create an HTTP session with the LPSC portal.

    Visits the portal homepage to pick up a session cookie, then
    all subsequent requests in this session will include it.
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                      'AppleWebKit/537.36',
    })

    log("Initializing portal session...")
    try:
        resp = session.get(f"{LPSC_PORTAL_URL}/PSC/DocumentSearch", timeout=30)
        resp.raise_for_status()
        log(f"Session initialized (cookies: {list(session.cookies.keys())})")
    except requests.exceptions.RequestException as e:
        print(f"WARNING: Could not initialize portal session: {e}")

    return session


def search_docket_documents(session: requests.Session, docket_number: str,
                            start_date: datetime, end_date: datetime) -> List[Dict]:
    """
    Search the LPSC portal for documents filed for a docket in a date range.

    Uses the Kendo ASP.NET MVC format that the portal expects.

    Args:
        session: An authenticated requests session (from create_session())
        docket_number: The docket number to search (e.g., "U-36625")
        start_date: Start of the date window
        end_date: End of the date window

    Returns:
        List of document metadata dicts from the API, each containing:
        OrderId, Description, DocumentNumber, DocumentType, FilingType, DateFiled
    """
    start_str = f"{start_date.month}/{start_date.day}/{start_date.year}"
    end_str = f"{end_date.month}/{end_date.day}/{end_date.year}"

    log(f"Searching documents for {docket_number} from {start_str} to {end_str}")

    params = {
        'sort': 'DateFiled-desc',
        'page': '1',
        'pageSize': '50',
        'skip': '0',
        'take': '50',
        'paramSet[DocketNumber]': docket_number,
        'paramSet[StartDate]': start_str,
        'paramSet[EndDate]': end_str,
    }

    headers = {
        'X-Requested-With': 'XMLHttpRequest',
    }

    try:
        resp = session.post(DOCUMENT_SEARCH_URL, data=params,
                            headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        print(f"  ERROR: Document search failed for {docket_number}: {e}")
        return []
    except ValueError:
        print(f"  ERROR: Invalid JSON response for {docket_number}")
        return []

    documents = data.get('Data', [])
    total = data.get('Total', 0)
    log(f"Found {total} document(s) for {docket_number} in date range")

    return documents


def get_document_details_url(order_id) -> str:
    """Build a DocumentDetails URL from an OrderId."""
    return f"{LPSC_PORTAL_URL}/PSC/DocumentDetails?documentId={order_id}"


def get_docket_details_url(matter_id) -> str:
    """Build a DocketDetails URL from a MatterId."""
    return f"{LPSC_PORTAL_URL}/PSC/DocketDetails?docketId={matter_id}"


def extract_matter_id(document: Dict, docket_number: str) -> str:
    """
    Extract the MatterId for a docket number from a document's Dockets array.

    The portal API returns documents with a 'Dockets' list, each containing
    MatterId (numeric ID) and MatterNumber (e.g. 'U-37584'). The MatterId
    is needed to build a working DocketDetails URL.

    Returns the MatterId as a string, or empty string if not found.
    """
    for docket in document.get('Dockets', []):
        if docket.get('MatterNumber', '').upper() == docket_number.upper():
            return str(docket.get('MatterId', ''))
    return ''
