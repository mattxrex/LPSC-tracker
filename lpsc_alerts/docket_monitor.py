"""
Docket Monitor — Path 2: Direct Docket Tracking

Polls the LPSC portal API for new documents filed on dockets that
users have specifically asked to track. No bulletin needed — this
catches filings between bulletins.

Pipeline:
  Get all tracked dockets → search portal for new docs (last 30 days) →
  for each user tracking that docket: queue alerts for unseen docs
"""

from datetime import datetime, timedelta
from typing import List, Dict

from config import DOCKET_DOCUMENT_LOOKBACK_DAYS, log
import database as db
from portal_api import (create_session, search_docket_documents,
                        get_document_details_url, get_docket_details_url,
                        extract_matter_id)


def check_tracked_dockets() -> List[Dict]:
    """
    Poll the portal for new documents on all tracked dockets.

    Returns a list of alert dicts ready to be sent:
    [
        {
            'user_id': 1,
            'email': 'alice@example.com',
            'alert_type': 'docket_update',
            'docket_number': 'U-36625',
            'document_id': '12345',
            'document_description': 'Application for Rate Adjustment',
            'document_type': 'Filing',
            'date_filed': '2/7/2026',
            'details_url': 'https://...',
        },
        ...
    ]
    """
    alerts = []

    # Get all tracked dockets across all active users
    all_tracked = db.get_all_tracked_dockets()
    if not all_tracked:
        log("No tracked dockets found, skipping docket check")
        return alerts

    # Group by docket number (multiple users may track the same docket)
    docket_users = {}
    for td in all_tracked:
        docket_num = td['docket_number']
        if docket_num not in docket_users:
            docket_users[docket_num] = []
        docket_users[docket_num].append({
            'user_id': td['user_id'],
            'email': td['email'],
        })

    print(f"Checking {len(docket_users)} tracked docket(s)...")

    # Set up date range: last N days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=DOCKET_DOCUMENT_LOOKBACK_DAYS)

    # Create a portal session
    session = create_session()

    for docket_number, users in docket_users.items():
        # Skip non-searchable docket types
        if docket_number.startswith('SPECIAL') or docket_number.startswith('GENERAL'):
            log(f"Skipping {docket_number} (not searchable)")
            continue

        print(f"  Checking {docket_number}...")

        documents = search_docket_documents(
            session, docket_number, start_date, end_date
        )

        if not documents:
            print(f"    No documents in last {DOCKET_DOCUMENT_LOOKBACK_DAYS} days")
            continue

        print(f"    Found {len(documents)} document(s)")

        # Extract the docket's MatterId from the first document for the
        # DocketDetails link (same ID across all docs for this docket)
        matter_id = extract_matter_id(documents[0], docket_number)
        docket_url = get_docket_details_url(matter_id) if matter_id else ''

        for doc in documents:
            order_id = str(doc.get('OrderId', ''))
            description = doc.get('Description', '')
            doc_type = doc.get('FilingType', '') or doc.get('DocumentType', '')
            date_filed = doc.get('DateFiled', '')
            details_url = get_document_details_url(order_id)

            # Skip bulletin documents
            if doc.get('FilingType') == 'Bulletin':
                continue

            # Alert each user tracking this docket
            for user in users:
                # Check if already alerted
                if db.was_alert_sent(user['user_id'], docket_number,
                                     document_id=order_id):
                    continue

                alerts.append({
                    'user_id': user['user_id'],
                    'email': user['email'],
                    'alert_type': 'docket_update',
                    'docket_number': docket_number,
                    'docket_url': docket_url,
                    'document_id': order_id,
                    'document_description': description,
                    'document_type': doc_type,
                    'date_filed': date_filed,
                    'details_url': details_url,
                })

    print(f"\nDocket check complete: {len(alerts)} docket update alert(s) queued.")
    return alerts
