"""
LPSC Alerts — Multi-User Docket Monitoring Tool

CLI for managing users and running alert checks. Two monitoring paths:
1. Keyword discovery — parse new bulletins, match against user keywords
2. Direct docket tracking — poll portal for new docs on tracked dockets

Both paths feed into one concise email per user.

Usage:
    python main.py add-user EMAIL [--keywords K] [--exclude K] [--dockets D]
    python main.py remove-user EMAIL
    python main.py list-users
    python main.py update-user EMAIL [--add-keywords K] [--remove-keywords K]
                                     [--add-exclude K] [--remove-exclude K]
                                     [--add-dockets D] [--remove-dockets D]
    python main.py check          # One-shot: bulletins + dockets → alerts
    python main.py monitor        # Continuous: check every 24 hours
    python main.py test-alert EMAIL
"""

import sys
import time
import re
import argparse
from datetime import datetime, timedelta

import database as db
import user_manager
from bulletin_monitor import check_bulletins, fetch_rss_feed, extract_pdf_url
from docket_monitor import check_tracked_dockets
from alert_generator import (generate_alert_email, generate_user_notification_email,
                             generate_user_removal_email)
from email_sender import send_alert_email
from portal_api import (create_session, search_docket_documents,
                        get_document_details_url, get_docket_details_url,
                        extract_matter_id)
from bulletin_downloader import download_bulletin_by_url
from bulletin_parser import parse_bulletin
from keyword_matcher import match_keywords
from config import MONITOR_INTERVAL, DOCKET_DOCUMENT_LOOKBACK_DAYS, log


def send_alerts(all_alerts):
    """
    Group alerts by user, generate emails, send them, and record
    in sent_alerts to prevent future duplicates.

    Args:
        all_alerts: List of alert dicts from bulletin_monitor and docket_monitor

    Returns:
        Number of emails sent
    """
    if not all_alerts:
        print("\nNo alerts to send.")
        return 0

    # Group by user
    by_user = {}
    for alert in all_alerts:
        uid = alert['user_id']
        if uid not in by_user:
            by_user[uid] = []
        by_user[uid].append(alert)

    emails_sent = 0

    for user_id, user_alerts in by_user.items():
        email_data = generate_alert_email(user_alerts)
        if not email_data:
            continue

        print(f"\nSending {len(user_alerts)} alert(s) to {email_data['recipient']}...")

        success = send_alert_email(
            recipient=email_data['recipient'],
            subject=email_data['subject'],
            html_content=email_data['html'],
        )

        if success:
            emails_sent += 1
            # Record each alert as sent
            for alert in user_alerts:
                db.record_sent_alert(
                    user_id=alert['user_id'],
                    docket_number=alert['docket_number'],
                    alert_type=alert['alert_type'],
                    bulletin_number=alert.get('bulletin_number'),
                    document_id=alert.get('document_id'),
                )
        else:
            print(f"  WARNING: Email failed for {email_data['recipient']}")

    return emails_sent


def _fetch_recent_docs_for_docket(session, docket_number, start_date, end_date):
    """
    Search the portal for recent documents on a single docket.

    Returns a tuple of (docs_list, docket_url) where docs_list contains
    alert-style dicts for the most recent filing date only, and docket_url
    is the DocketDetails URL (or empty string if not found).
    """
    # Skip non-searchable docket types
    if docket_number.startswith('SPECIAL') or docket_number.startswith('GENERAL'):
        return [], ''

    documents = search_docket_documents(
        session, docket_number, start_date, end_date
    )

    if not documents:
        return [], ''

    # Extract the MatterId for the DocketDetails link
    matter_id = extract_matter_id(documents[0], docket_number)
    docket_url = get_docket_details_url(matter_id) if matter_id else ''

    # Parse JS timestamps and group by filing date
    date_groups = {}
    for doc in documents:
        if doc.get('FilingType') == 'Bulletin':
            continue

        raw_date = doc.get('DateFiled', '')
        match = re.search(r'/Date\((\d+)\)/', str(raw_date))
        if match:
            ts = int(match.group(1)) / 1000
            filed_date = datetime.fromtimestamp(ts)
            date_str = filed_date.strftime('%-m/%-d/%Y')
        else:
            date_str = str(raw_date)

        if date_str not in date_groups:
            date_groups[date_str] = []
        date_groups[date_str].append(doc)

    if not date_groups:
        return [], docket_url

    # Keep only the most recent date's documents
    most_recent_date = sorted(date_groups.keys(), reverse=True)[0]
    docs_list = []
    for doc in date_groups[most_recent_date]:
        order_id = str(doc.get('OrderId', ''))
        docs_list.append({
            'docket_number': docket_number,
            'docket_url': docket_url,
            'document_description': doc.get('Description', ''),
            'document_type': doc.get('FilingType', '') or doc.get('DocumentType', ''),
            'date_filed': most_recent_date,
            'details_url': get_document_details_url(order_id),
        })

    return docs_list, docket_url


def send_user_notification(email: str, is_new_user: bool):
    """
    Send a welcome or settings-updated notification email to a user.

    Looks up the user's settings, fetches recent documents for their
    tracked dockets from the LPSC portal, checks the latest bulletin for
    keyword matches, and sends a notification email showing their current
    configuration and recent activity.

    Args:
        email: The user's email address
        is_new_user: True for "added" message, False for "updated" message
    """
    user = db.get_user_by_email(email)
    if not user:
        print(f"WARNING: Could not find user {email} for notification.")
        return

    dockets = db.get_tracked_dockets(user['id'])
    recent_docs = []
    keyword_docs = []
    docket_urls = {}  # docket_number → DocketDetails URL

    has_dockets = bool(dockets)
    has_keywords = bool(user.get('include_keywords'))

    # Create a single portal session if we need to fetch any documents
    session = None
    if has_dockets or has_keywords:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=DOCKET_DOCUMENT_LOOKBACK_DAYS)
        session = create_session()

    # --- Tracked dockets: fetch recent docs from the portal ---
    if has_dockets:
        print(f"Fetching recent activity for {len(dockets)} tracked docket(s)...")
        for docket_number in dockets:
            docs, docket_url = _fetch_recent_docs_for_docket(
                session, docket_number, start_date, end_date
            )
            if docket_url:
                docket_urls[docket_number] = docket_url
            recent_docs.extend(docs)

    # --- Keywords: check the latest bulletin for matches ---
    if has_keywords:
        print("Checking latest bulletin for keyword matches...")

        feed_entries = fetch_rss_feed()
        if feed_entries:
            # Use the first (most recent) bulletin from the RSS feed
            latest = feed_entries[0]
            pdf_url = extract_pdf_url(latest['details_url'])

            if pdf_url:
                pdf_path = download_bulletin_by_url(pdf_url, latest['number'])
                if pdf_path:
                    docket_entries = parse_bulletin(str(pdf_path))
                    print(f"Parsed {len(docket_entries)} docket entries from bulletin #{latest['number']}")

                    # Clean up the downloaded PDF
                    try:
                        pdf_path.unlink()
                    except OSError:
                        pass

                    # Match each docket entry against the user's keywords
                    matched_dockets = {}  # docket_number → matched_keywords list
                    for docket in docket_entries:
                        match_text = f"{docket.title} {docket.raw_text}"
                        is_relevant, matched = match_keywords(
                            match_text,
                            user['include_keywords'],
                            user.get('exclude_keywords', ''),
                        )
                        if is_relevant:
                            if docket.docket_number not in matched_dockets:
                                matched_dockets[docket.docket_number] = set()
                            matched_dockets[docket.docket_number].update(matched)

                    if matched_dockets:
                        print(f"Found {len(matched_dockets)} docket(s) matching keywords.")

                        # Fetch recent portal docs for each matching docket
                        for docket_number, kw_set in matched_dockets.items():
                            docs, docket_url = _fetch_recent_docs_for_docket(
                                session, docket_number, start_date, end_date
                            )
                            # Add matched_keywords to each doc
                            for doc in docs:
                                doc['matched_keywords'] = sorted(kw_set)
                            if docket_url:
                                docket_urls[docket_number] = docket_url
                            keyword_docs.extend(docs)
                    else:
                        print("No keyword matches found in latest bulletin.")

    # Generate and send the notification email
    email_data = generate_user_notification_email(
        user, dockets, recent_docs, is_new_user,
        docket_urls=docket_urls, keyword_docs=keyword_docs,
    )

    action = "welcome" if is_new_user else "update notification"
    print(f"Sending {action} email to {email}...")

    success = send_alert_email(
        recipient=email_data['recipient'],
        subject=email_data['subject'],
        html_content=email_data['html'],
    )

    if success:
        print(f"Notification email sent to {email}.")
    else:
        print(f"WARNING: Notification email failed for {email}.")


def cmd_check():
    """Run one check cycle: bulletins + tracked dockets → send alerts."""
    db.init_database()

    print("=" * 60)
    print("LPSC Alerts — Running check")
    print("=" * 60)

    # Path 1: Bulletin keyword discovery
    print("\n--- Path 1: Checking for new bulletins ---")
    bulletin_alerts = check_bulletins()

    # Path 2: Tracked docket polling
    print("\n--- Path 2: Checking tracked dockets ---")
    docket_alerts = check_tracked_dockets()

    # Combine and send
    all_alerts = bulletin_alerts + docket_alerts
    print(f"\n--- Sending alerts ({len(all_alerts)} total) ---")
    emails_sent = send_alerts(all_alerts)

    print(f"\n{'='*60}")
    print("CHECK COMPLETE")
    print(f"{'='*60}")
    print(f"Keyword matches:  {len(bulletin_alerts)}")
    print(f"Docket updates:   {len(docket_alerts)}")
    print(f"Emails sent:      {emails_sent}")
    print(f"{'='*60}")


def cmd_monitor():
    """Continuously run check cycles every MONITOR_INTERVAL seconds."""
    db.init_database()

    print("LPSC Alerts — Continuous monitoring")
    print(f"Checking every {MONITOR_INTERVAL // 3600} hours. Ctrl+C to stop.\n")

    while True:
        try:
            cmd_check()
            print(f"\nNext check in {MONITOR_INTERVAL // 3600} hours...")
            time.sleep(MONITOR_INTERVAL)
        except KeyboardInterrupt:
            print("\nMonitoring stopped.")
            break


def cmd_test_alert(email: str):
    """Send a test email to verify email setup works."""
    db.init_database()

    test_html = """
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 640px; margin: 0 auto; padding: 20px;">
  <div style="background-color: #2b6cb0; color: white; padding: 16px 20px;
              border-radius: 8px 8px 0 0;">
    <h2 style="margin: 0; font-size: 18px;">LPSC Alert — Test</h2>
  </div>
  <div style="padding: 20px; border: 1px solid #e2e8f0; border-top: none;
              border-radius: 0 0 8px 8px;">
    <p style="color: #333; font-size: 14px;">
      This is a test email from LPSC Alerts. If you received this,
      your email configuration is working correctly.
    </p>
  </div>
</div>
"""
    success = send_alert_email(email, "LPSC Alert — Test Email", test_html)
    if success:
        print("Test email sent successfully!")
    else:
        print("Test email failed. Check your .env configuration.")


def main():
    parser = argparse.ArgumentParser(
        description="LPSC Alerts — Multi-User Docket Monitoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # add-user
    p_add = subparsers.add_parser('add-user', help='Add a new user')
    p_add.add_argument('email', help='User email address')
    p_add.add_argument('--keywords', default='', help='Comma-separated include keywords')
    p_add.add_argument('--exclude', default='', help='Comma-separated exclude keywords')
    p_add.add_argument('--dockets', default='', help='Comma-separated docket numbers to track')

    # remove-user
    p_rm = subparsers.add_parser('remove-user', help='Remove a user')
    p_rm.add_argument('email', help='User email address')

    # list-users
    subparsers.add_parser('list-users', help='List all users')

    # update-user
    p_up = subparsers.add_parser('update-user', help='Update a user')
    p_up.add_argument('email', help='User email address')
    p_up.add_argument('--add-keywords', help='Keywords to add')
    p_up.add_argument('--remove-keywords', help='Keywords to remove')
    p_up.add_argument('--add-exclude', help='Exclusion keywords to add')
    p_up.add_argument('--remove-exclude', help='Exclusion keywords to remove')
    p_up.add_argument('--add-dockets', help='Dockets to start tracking')
    p_up.add_argument('--remove-dockets', help='Dockets to stop tracking')

    # check
    subparsers.add_parser('check', help='One-shot: check bulletins + dockets, send alerts')

    # monitor
    subparsers.add_parser('monitor', help='Continuous: check every 24 hours')

    # test-alert
    p_test = subparsers.add_parser('test-alert', help='Send a test email')
    p_test.add_argument('email', help='Email to send test to')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize database for user management commands
    if args.command in ('add-user', 'remove-user', 'list-users', 'update-user'):
        db.init_database()

    if args.command == 'add-user':
        user_manager.add_user(args.email, args.keywords, args.exclude, args.dockets)
        send_user_notification(args.email, is_new_user=True)

    elif args.command == 'remove-user':
        # Send removal notification before deleting user data
        user = db.get_user_by_email(args.email)
        if user:
            email_data = generate_user_removal_email(args.email)
            print(f"Sending removal notification to {args.email}...")
            success = send_alert_email(
                recipient=email_data['recipient'],
                subject=email_data['subject'],
                html_content=email_data['html'],
            )
            if success:
                print(f"Removal notification sent to {args.email}.")
            else:
                print(f"WARNING: Removal notification failed for {args.email}.")
        user_manager.remove_user(args.email)

    elif args.command == 'list-users':
        user_manager.list_users()

    elif args.command == 'update-user':
        user_manager.update_user(
            args.email,
            add_keywords=args.add_keywords,
            remove_keywords=args.remove_keywords,
            add_exclude=args.add_exclude,
            remove_exclude=args.remove_exclude,
            add_dockets=args.add_dockets,
            remove_dockets=args.remove_dockets,
        )
        send_user_notification(args.email, is_new_user=False)

    elif args.command == 'check':
        cmd_check()

    elif args.command == 'monitor':
        cmd_monitor()

    elif args.command == 'test-alert':
        cmd_test_alert(args.email)


if __name__ == '__main__':
    main()
