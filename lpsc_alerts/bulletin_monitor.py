"""
Bulletin Monitor — Path 1: Keyword Discovery

Fetches new LPSC bulletins via RSS, parses them, and matches docket
entries against each user's keywords. Discovers things users didn't
know to look for.

Pipeline:
  RSS feed → find new bulletins → download PDF → parse docket entries →
  for each user: match keywords → queue alerts
"""

import re
import feedparser
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

from config import LPSC_RSS_URL, LPSC_BASE_URL, log
import database as db
from bulletin_parser import parse_bulletin, extract_text_from_pdf, extract_bulletin_date
from bulletin_downloader import download_bulletin_by_url
from keyword_matcher import match_keywords


def fetch_rss_feed() -> List[Dict]:
    """
    Fetch the LPSC RSS feed and return a list of bulletin entries.

    Each entry has: number, title, date, details_url
    """
    log(f"Fetching RSS feed: {LPSC_RSS_URL}")

    try:
        feed = feedparser.parse(LPSC_RSS_URL)
    except Exception as e:
        print(f"ERROR: Failed to fetch RSS feed: {e}")
        return []

    if feed.bozo and not feed.entries:
        print(f"ERROR: RSS feed parse error: {feed.bozo_exception}")
        return []

    bulletins = []
    for entry in feed.entries:
        guid = getattr(entry, 'id', '') or getattr(entry, 'guid', '')
        title = getattr(entry, 'title', '')

        number = None
        for text in [guid, title]:
            match = re.search(r'#?(\d{3,4})', text)
            if match:
                number = int(match.group(1))
                break

        if number is None:
            log(f"Skipping RSS entry (no bulletin number found): {title}")
            continue

        link = getattr(entry, 'link', '')
        if link and not link.startswith('http'):
            link = LPSC_BASE_URL + link

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

    soup = BeautifulSoup(response.text, 'html.parser')
    for link in soup.find_all('a', href=True):
        href = link['href']
        if 'ViewFile' in href and 'fileId' in href:
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


def check_bulletins() -> List[Dict]:
    """
    Check for new bulletins and match against user keywords.

    Returns a list of alert dicts ready to be sent:
    [
        {
            'user_id': 1,
            'email': 'alice@example.com',
            'alert_type': 'keyword_match',
            'bulletin_number': 1370,
            'docket_number': 'U-37800',
            'title': 'Entergy Louisiana solar facility...',
            'matched_keywords': ['solar', 'Entergy'],
            'subpart': 'C',
        },
        ...
    ]
    """
    alerts = []

    # Get active users who have keywords configured
    users = db.get_all_active_users()
    keyword_users = [u for u in users if u.get('include_keywords')]

    if not keyword_users:
        log("No users with keywords configured, skipping bulletin check")
        return alerts

    # Fetch RSS feed for new bulletins
    feed_entries = fetch_rss_feed()
    if not feed_entries:
        print("No bulletins found in RSS feed.")
        return alerts

    # Check which bulletins are new
    new_bulletins = []
    for entry in feed_entries:
        existing = db.get_bulletin(entry['number'])
        if existing:
            log(f"Bulletin #{entry['number']} already processed, skipping")
        else:
            new_bulletins.append(entry)

    if not new_bulletins:
        print("No new bulletins. Database is up to date.")
        return alerts

    print(f"Found {len(new_bulletins)} new bulletin(s) to process.")

    # Process each new bulletin
    for entry in new_bulletins:
        number = entry['number']
        print(f"\n--- Processing bulletin #{number} ---")

        # Find and download the PDF
        pdf_url = extract_pdf_url(entry['details_url'])
        if not pdf_url:
            print(f"ERROR: Could not find PDF for bulletin #{number}")
            continue

        pdf_path = download_bulletin_by_url(pdf_url, number)
        if not pdf_path:
            print(f"ERROR: Could not download bulletin #{number}")
            continue

        # Parse docket entries
        docket_entries = parse_bulletin(str(pdf_path))
        print(f"Parsed {len(docket_entries)} docket entries from bulletin #{number}")

        # Extract bulletin date from PDF text
        full_text = extract_text_from_pdf(str(pdf_path))
        bulletin_date = extract_bulletin_date(full_text)

        # Record the bulletin as processed
        db.add_bulletin(number, date=bulletin_date or entry.get('date'),
                        pdf_path=str(pdf_path))

        # Clean up the downloaded PDF
        try:
            pdf_path.unlink()
            log(f"Cleaned up: {pdf_path}")
        except OSError:
            pass

        # Match each docket against each user's keywords
        for docket in docket_entries:
            # Build the text to match against (title + raw text)
            match_text = f"{docket.title} {docket.raw_text}"

            for user in keyword_users:
                # Check if we already alerted this user about this docket in this bulletin
                if db.was_alert_sent(user['id'], docket.docket_number,
                                     bulletin_number=number):
                    continue

                is_relevant, matched = match_keywords(
                    match_text,
                    user['include_keywords'],
                    user.get('exclude_keywords', ''),
                )

                if is_relevant:
                    alerts.append({
                        'user_id': user['id'],
                        'email': user['email'],
                        'alert_type': 'keyword_match',
                        'bulletin_number': number,
                        'docket_number': docket.docket_number,
                        'title': docket.title,
                        'matched_keywords': matched,
                        'subpart': docket.subpart,
                    })

    print(f"\nBulletin check complete: {len(alerts)} keyword match alert(s) queued.")
    return alerts
