"""
RSS Monitor for LPSC Bulletins

This module handles automatic detection of new LPSC bulletins via their
RSS feed. It fetches the feed, identifies bulletins we haven't processed
yet, finds their PDF download links, and triggers processing.

How it works:
1. Fetch the LPSC RSS feed (lists recent bulletins)
2. Compare against our database to find new ones
3. Visit each new bulletin's DocumentDetails page to find the PDF link
4. Hand off to the existing process_bulletin() pipeline
"""

import re
import feedparser
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

from config import LPSC_RSS_URL, LPSC_BASE_URL, log
import database as db


def fetch_rss_feed() -> List[Dict]:
    """
    Fetch the LPSC RSS feed and parse it into a list of bulletin entries.

    Each entry in the returned list is a dict with:
        - number: int, the bulletin number (e.g., 1368)
        - title: str, the raw title from the feed
        - date: str, the publication date
        - details_url: str, full URL to the DocumentDetails page

    Returns:
        List of bulletin entry dicts, or empty list on error.
    """
    log(f"Fetching RSS feed: {LPSC_RSS_URL}")

    try:
        # Fetch with an explicit timeout, then hand the bytes to feedparser.
        # feedparser.parse(url) does its own fetch with NO timeout, which once
        # let a single stalled connection freeze the scheduled job for months.
        resp = requests.get(LPSC_RSS_URL, timeout=30)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as e:
        print(f"ERROR: Failed to fetch RSS feed: {e}")
        return []

    if feed.bozo and not feed.entries:
        print(f"ERROR: RSS feed parse error: {feed.bozo_exception}")
        return []

    bulletins = []

    for entry in feed.entries:
        # Extract bulletin number from the title/guid
        # Expected format: "Bulletin #1368" or similar
        guid = getattr(entry, 'id', '') or getattr(entry, 'guid', '')
        title = getattr(entry, 'title', '')

        # Try to find the bulletin number in guid first, then title
        number = None
        for text in [guid, title]:
            match = re.search(r'#?(\d{3,4})', text)
            if match:
                number = int(match.group(1))
                break

        if number is None:
            log(f"Skipping RSS entry (no bulletin number found): {title}")
            continue

        # Get the link to the DocumentDetails page
        link = getattr(entry, 'link', '')
        if link and not link.startswith('http'):
            link = LPSC_BASE_URL + link

        # Get publication date
        pub_date = getattr(entry, 'published', '')

        bulletins.append({
            'number': number,
            'title': title,
            'date': pub_date,
            'details_url': link,
        })

        log(f"Found bulletin #{number}: {title}")

    log(f"RSS feed returned {len(bulletins)} bulletin(s)")
    return bulletins


def extract_pdf_url(details_url: str) -> Optional[str]:
    """
    Visit a DocumentDetails page and find the PDF download link.

    The page contains a link with 'ViewFile?fileId=' that points to
    the actual PDF. We find that link and return the full URL.

    Args:
        details_url: Full URL to the DocumentDetails page

    Returns:
        Full URL to the PDF file, or None if not found.
    """
    log(f"Fetching document details: {details_url}")

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36',
        }
        response = requests.get(details_url, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to fetch document details page: {e}")
        return None

    # Parse the HTML and look for ViewFile links
    soup = BeautifulSoup(response.text, 'html.parser')

    for link in soup.find_all('a', href=True):
        href = link['href']
        if 'ViewFile' in href and 'fileId' in href:
            # Build the full URL
            if href.startswith('http'):
                pdf_url = href
            elif href.startswith('/'):
                pdf_url = LPSC_BASE_URL + href
            else:
                pdf_url = LPSC_BASE_URL + '/' + href

            log(f"Found PDF URL: {pdf_url}")
            return pdf_url

    print(f"WARNING: No PDF link found on page: {details_url}")
    return None


def check_for_new_bulletins() -> Dict:
    """
    Check the RSS feed for new bulletins and process any that are found.

    This is the main orchestrator function. It:
    1. Fetches the RSS feed to see what bulletins are available
    2. Checks the database to see which ones we've already processed
    3. For each new bulletin, finds the PDF link and processes it
    4. Returns a summary of what happened

    Returns:
        Dict with keys:
            - feed_count: how many bulletins the RSS feed listed
            - new_count: how many were new (not in our database)
            - processed: list of bulletin numbers that were processed
            - errors: list of bulletin numbers that failed
    """
    # Import here to avoid circular imports (main.py imports us,
    # and we need process_bulletin from main.py)
    from main import process_bulletin

    db.init_database()

    summary = {
        'feed_count': 0,
        'new_count': 0,
        'processed': [],
        'errors': [],
    }

    # Step 1: Fetch the RSS feed
    feed_entries = fetch_rss_feed()
    summary['feed_count'] = len(feed_entries)

    if not feed_entries:
        print("No bulletins found in RSS feed.")
        return summary

    # Step 2: Check which bulletins are new
    new_bulletins = []
    for entry in feed_entries:
        existing = db.get_bulletin(entry['number'])
        if existing:
            log(f"Bulletin #{entry['number']} already in database, skipping")
        else:
            new_bulletins.append(entry)

    summary['new_count'] = len(new_bulletins)

    if not new_bulletins:
        print("No new bulletins found. Database is up to date.")
        return summary

    print(f"Found {len(new_bulletins)} new bulletin(s) to process.")

    # Step 3: Process each new bulletin
    for entry in new_bulletins:
        number = entry['number']
        print(f"\n--- Processing new bulletin #{number} ---")

        # Find the PDF URL from the DocumentDetails page
        pdf_url = extract_pdf_url(entry['details_url'])

        if not pdf_url:
            print(f"ERROR: Could not find PDF link for bulletin #{number}")
            summary['errors'].append(number)
            continue

        # Process the bulletin using the existing pipeline
        success = process_bulletin(pdf_url, number, date=entry.get('date'))

        if success:
            summary['processed'].append(number)
        else:
            summary['errors'].append(number)

    return summary
