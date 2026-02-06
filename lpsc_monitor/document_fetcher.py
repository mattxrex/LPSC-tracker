"""
Document Fetcher for LPSC Docket Documents

This module downloads documents filed for specific dockets from the LPSC portal.
It only fetches "new" documents — those filed within the bulletin's date window
(roughly the ~2 weeks since the previous bulletin), keeping downloads small and
focused.

How it works:
1. Look up a bulletin and its relevant dockets from the database
2. Calculate the date window (bulletin date minus DOCUMENT_DATE_WINDOW_DAYS)
3. For each docket, search the LPSC Document Search API for docs in that window
4. Download each new PDF and record it in the documents table

Reuses existing code:
- rss_monitor.extract_pdf_url() to scrape PDF links from DocumentDetails pages
- bulletin_downloader.download_file() to download and validate PDFs
"""

import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from config import (
    LPSC_PORTAL_URL, LPSC_BASE_URL, DOCUMENT_SEARCH_URL,
    DOCUMENT_DATE_WINDOW_DAYS, DOCUMENTS_DIR, log
)
import database as db
from rss_monitor import extract_pdf_url
from bulletin_downloader import download_file


def create_session() -> requests.Session:
    """
    Create an HTTP session with the LPSC portal.

    The Document Search API requires:
    1. An ASP.NET session cookie (obtained by visiting the portal first)
    2. The X-Requested-With: XMLHttpRequest header on POST requests

    We GET the portal homepage first to pick up the session cookie,
    then all subsequent requests in this session will include it.
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                      'AppleWebKit/537.36',
    })

    # Visit the portal to get a session cookie
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
    # Format dates as M/d/yyyy (what the LPSC portal expects)
    start_str = f"{start_date.month}/{start_date.day}/{start_date.year}"
    end_str = f"{end_date.month}/{end_date.day}/{end_date.year}"

    log(f"Searching documents for {docket_number} from {start_str} to {end_str}")

    # Build the request parameters in Kendo ASP.NET MVC format
    # IMPORTANT: sort uses hyphen format (DateFiled-desc), not array format
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


def fetch_documents_for_docket(session: requests.Session, docket_id: int,
                               docket_number: str, start_date: datetime,
                               end_date: datetime) -> Dict:
    """
    Search for and download new documents for a single docket.

    For each document found in the date window:
    1. Check if we've already downloaded it (dedup by URL)
    2. Get the PDF download link from the DocumentDetails page
    3. Download the PDF to data/documents/{docket_number}/
    4. Record it in the documents table

    Args:
        session: HTTP session with portal cookies
        docket_id: Database ID of the docket
        docket_number: Docket number (e.g., "U-36625")
        start_date: Start of date window
        end_date: End of date window

    Returns:
        Dict with counts: downloaded, skipped, errors
    """
    result = {'downloaded': 0, 'skipped': 0, 'errors': 0}

    # Search for documents in the date window
    documents = search_docket_documents(session, docket_number, start_date, end_date)

    if not documents:
        return result

    # Create the docket's document directory
    docket_dir = DOCUMENTS_DIR / docket_number
    docket_dir.mkdir(parents=True, exist_ok=True)

    for doc in documents:
        order_id = doc.get('OrderId')
        doc_number = doc.get('DocumentNumber', 'unknown')
        filing_type = doc.get('FilingType', '')
        doc_type = filing_type or doc.get('DocumentType', '')

        # Skip bulletin documents — we already have those in data/bulletins/
        if filing_type == 'Bulletin':
            log(f"  Skipping bulletin document: {doc_number}")
            continue
        description = doc.get('Description', '')
        date_filed = doc.get('DateFiled', '')

        # The DocumentDetails URL for this document
        details_url = f"{LPSC_PORTAL_URL}/PSC/DocumentDetails?documentId={order_id}"

        # Check if we already have this document (dedup)
        existing = db.get_document_by_url(details_url)
        if existing:
            log(f"  Already downloaded: {doc_number}")
            result['skipped'] += 1
            continue

        print(f"    {doc_number}: {description[:60]}...")
        print(f"      Type: {doc_type} | Filed: {date_filed}")

        # Get the PDF download link from the DocumentDetails page
        pdf_url = extract_pdf_url(details_url)
        if not pdf_url:
            print(f"      WARNING: No PDF link found, skipping")
            result['errors'] += 1
            continue

        # Download the PDF
        save_path = docket_dir / f"{doc_number}.pdf"

        if save_path.exists():
            log(f"  File already exists: {save_path}")
        else:
            success = download_file(pdf_url, save_path)
            if not success:
                print(f"      WARNING: Download failed, skipping")
                result['errors'] += 1
                continue

        # Record in database
        db.add_document(
            docket_id=docket_id,
            document_url=details_url,
            document_type=doc_type,
            pdf_path=str(save_path),
        )
        result['downloaded'] += 1
        print(f"      Saved: {save_path.name}")

    return result


def fetch_documents_for_bulletin(bulletin_number: int = None):
    """
    Main orchestrator: fetch new docket documents for a bulletin.

    If no bulletin_number is given, uses the latest bulletin in the database.

    Steps:
    1. Look up the bulletin and its date
    2. Calculate the date window (bulletin_date - DOCUMENT_DATE_WINDOW_DAYS)
    3. Get all relevant dockets for this bulletin
    4. For each docket, search and download new documents
    5. Print a summary

    Args:
        bulletin_number: Specific bulletin number, or None for latest
    """
    db.init_database()

    # Step 1: Find the bulletin
    if bulletin_number:
        bulletin = db.get_bulletin(bulletin_number)
        if not bulletin:
            print(f"ERROR: Bulletin #{bulletin_number} not found in database.")
            print("Process it first with: python main.py check")
            return
    else:
        # Get the latest bulletin
        all_bulletins = db.get_all_bulletins()
        if not all_bulletins:
            print("ERROR: No bulletins in database. Run 'python main.py check' first.")
            return
        bulletin = all_bulletins[0]  # Already sorted most recent first
        bulletin_number = bulletin['number']

    print(f"\n{'='*60}")
    print(f"Fetching Documents for Bulletin #{bulletin_number}")
    print(f"{'='*60}")

    # Step 2: Calculate date window
    # Parse the bulletin date — try common formats
    bulletin_date = None
    if bulletin['date']:
        for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%B %d, %Y',
                    '%a, %d %b %Y %H:%M:%S %z', '%a, %d %b %Y %H:%M:%S %Z'):
            try:
                bulletin_date = datetime.strptime(bulletin['date'].strip(), fmt)
                break
            except ValueError:
                continue

    if not bulletin_date:
        print(f"WARNING: Could not parse bulletin date '{bulletin['date']}'")
        print("Using today's date as the end of the search window.")
        bulletin_date = datetime.now()

    # Look for a previous bulletin to use as the start date (more precise)
    all_bulletins = db.get_all_bulletins()
    start_date = None
    for b in all_bulletins:
        if b['number'] < bulletin_number:
            # This is the previous bulletin — try to parse its date
            if b['date']:
                for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%B %d, %Y',
                            '%a, %d %b %Y %H:%M:%S %z', '%a, %d %b %Y %H:%M:%S %Z'):
                    try:
                        start_date = datetime.strptime(b['date'].strip(), fmt)
                        break
                    except ValueError:
                        continue
            break

    if not start_date:
        # Fall back to the configured window
        start_date = bulletin_date - timedelta(days=DOCUMENT_DATE_WINDOW_DAYS)

    end_date = bulletin_date

    print(f"Date window: {start_date.strftime('%m/%d/%Y')} to {end_date.strftime('%m/%d/%Y')}")

    # Step 3: Get relevant dockets for this bulletin
    dockets = db.get_relevant_dockets(bulletin['id'])

    if not dockets:
        print("\nNo relevant dockets found for this bulletin.")
        return

    print(f"Found {len(dockets)} relevant docket(s) to check.\n")

    # Step 4: Create a session and fetch documents for each docket
    session = create_session()

    totals = {'downloaded': 0, 'skipped': 0, 'errors': 0}

    for docket in dockets:
        docket_num = docket['docket_number']
        # Skip SPECIAL ORDER and GENERAL ORDER entries — they don't have
        # searchable docket numbers in the document search
        if docket_num.startswith('SPECIAL') or docket_num.startswith('GENERAL'):
            log(f"Skipping {docket_num} (not searchable in document search)")
            continue

        print(f"  {docket_num}: {docket['title'][:50]}...")

        result = fetch_documents_for_docket(
            session=session,
            docket_id=docket['id'],
            docket_number=docket_num,
            start_date=start_date,
            end_date=end_date,
        )

        totals['downloaded'] += result['downloaded']
        totals['skipped'] += result['skipped']
        totals['errors'] += result['errors']

        if result['downloaded'] == 0 and result['skipped'] == 0 and result['errors'] == 0:
            print(f"    No new documents in date window.")

    # Step 5: Print summary
    print(f"\n{'='*60}")
    print("FETCH COMPLETE")
    print(f"{'='*60}")
    print(f"Downloaded:  {totals['downloaded']} new document(s)")
    print(f"Skipped:     {totals['skipped']} already downloaded")
    print(f"Errors:      {totals['errors']}")
    print(f"{'='*60}")
