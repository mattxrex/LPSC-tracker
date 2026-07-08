"""
Alert Generator for LPSC Alerts

Builds concise HTML emails for each user based on their queued alerts.
Groups keyword matches and docket updates into a single email per user.
"""

import html as html_mod
import re

from datetime import datetime, date, timezone
from typing import List, Dict, Optional
from config import LPSC_PORTAL_URL, SUBPART_SECTIONS, log

# The LPSC portal returns filing dates in a couple of shapes. Handle both.
_MS_DATE_RE = re.compile(r"/Date\((-?\d+)")

# LPSC filings are stamped in U.S. Central time. Convert to that zone so the
# calendar date is right year-round; fall back to UTC if tz data is missing.
try:
    from zoneinfo import ZoneInfo
    _CENTRAL = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover — only if system tz data is unavailable
    _CENTRAL = timezone.utc


def _parse_filing_date(raw) -> Optional[date]:
    """
    Parse an LPSC 'DateFiled' value into a date, or None if unparseable.

    The portal returns either Microsoft/ASP.NET JSON, e.g.
    '/Date(1782450000000)/' (milliseconds since the Unix epoch, UTC), or
    occasionally a plain 'M/D/YYYY' / 'YYYY-MM-DD' string.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw

    text = str(raw)
    m = _MS_DATE_RE.search(text)
    if m:
        try:
            dt = datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)
            return dt.astimezone(_CENTRAL).date()
        except (ValueError, OverflowError, OSError):
            return None

    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _format_filing_date(raw) -> str:
    """Render an LPSC 'DateFiled' value as e.g. 'June 26, 2026'."""
    d = _parse_filing_date(raw)
    if d is None:
        # Show the original text rather than a machine token if we can't parse it
        return str(raw) if raw else "Date unknown"
    return f"{d:%B} {d.day}, {d.year}"


def _docket_portal_link(docket_number: str) -> str:
    """Build a link to the LPSC portal homepage.

    The LPSC portal doesn't support direct docket or document search URL
    linking — both /PSC/DocumentSearch and /PSC/DocketSearch return 500
    errors when accessed via GET. We link to the portal homepage instead.
    """
    return f"{LPSC_PORTAL_URL}/PSC"


def _render_docket_updates(docket_alerts: List[Dict]) -> List[str]:
    """
    Render docket update alerts as HTML blocks.

    Groups by docket number, then by filing date within each docket.
    Returns a list of HTML strings to be joined into the email body.
    """
    html_parts = []

    # Group by docket number
    by_docket = {}
    for a in docket_alerts:
        dn = a['docket_number']
        if dn not in by_docket:
            by_docket[dn] = []
        by_docket[dn].append(a)

    for docket_num, items in sorted(by_docket.items()):
        # Use the direct DocketDetails URL if available, otherwise fall back
        docket_url = items[0].get('docket_url', '') if items else ''
        portal_link = docket_url or _docket_portal_link(docket_num)

        html_parts.append(f"""
    <div style="margin-bottom: 16px; padding: 12px; background: #f7fafc; border-radius: 6px; border: 1px solid #e2e8f0;">
      <strong style="color: #333; font-size: 14px;">{html_mod.escape(docket_num)}</strong>
      <br>
      <a href="{portal_link}" style="font-size: 12px; color: #2b6cb0; text-decoration: none;">
        View docket on LPSC website &rarr;</a>
""")
        # Group by filing date within this docket. Parse to a real date so we
        # can both sort correctly and display a readable label.
        by_date = {}
        for item in items:
            d = _parse_filing_date(item.get('date_filed'))
            by_date.setdefault(d, []).append(item)

        # Sort newest-first; any unparseable dates (None) sort to the end.
        for d in sorted(by_date.keys(), key=lambda x: x or date.min, reverse=True):
            date_items = by_date[d]
            date_label = f"{d:%B} {d.day}, {d.year}" if d else "Date unknown"
            html_parts.append(f"""
      <div style="margin: 8px 0 4px 8px; font-size: 13px; color: #4a5568; font-weight: 600;">
        {html_mod.escape(date_label)}
      </div>
      <ul style="list-style: none; padding: 0; margin: 0 0 0 8px;">
""")
            for item in date_items:
                desc = item.get('document_description', 'New filing')
                details_url = item.get('details_url', '')
                doc_type = item.get('document_type', '')
                type_label = f' <span style="font-size: 11px; color: #a0aec0;">({html_mod.escape(doc_type)})</span>' if doc_type else ''

                html_parts.append(f"""
        <li style="padding: 4px 0; font-size: 13px; color: #333;">
          <a href="{details_url}" style="color: #2b6cb0; text-decoration: none;">
            {html_mod.escape(desc[:150])}</a>{type_label}
        </li>
""")
            html_parts.append("      </ul>")

        html_parts.append("    </div>")

    return html_parts


def generate_alert_email(alerts: List[Dict]) -> Dict:
    """
    Build an HTML email for a single user from their queued alerts.

    Args:
        alerts: List of alert dicts, all for the same user.
                Mix of 'keyword_match' and 'docket_update' types.

    Returns:
        Dict with 'subject', 'html', 'recipient'
    """
    if not alerts:
        return None

    recipient = alerts[0]['email']

    # Separate the two alert types
    keyword_alerts = [a for a in alerts if a['alert_type'] == 'keyword_match']
    docket_alerts = [a for a in alerts if a['alert_type'] == 'docket_update']

    total = len(alerts)
    subject = f"LPSC Alert — {total} new item{'s' if total != 1 else ''}"

    # Build HTML
    html_parts = []

    # --- Header ---
    html_parts.append("""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 640px; margin: 0 auto; padding: 20px;">
  <div style="background-color: #2b6cb0; color: white; padding: 16px 20px;
              border-radius: 8px 8px 0 0;">
    <h2 style="margin: 0; font-size: 18px;">LPSC Alert</h2>
    <p style="margin: 4px 0 0; font-size: 13px; opacity: 0.85;">
      Louisiana Public Service Commission</p>
  </div>
  <div style="padding: 20px; border: 1px solid #e2e8f0; border-top: none;
              border-radius: 0 0 8px 8px;">
""")

    # --- Keyword Matches ---
    if keyword_alerts:
        html_parts.append("""
    <h3 style="color: #2b6cb0; font-size: 15px; margin: 20px 0 10px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px;">
      Dockets Matching Your Keywords
    </h3>
""")
        # Group by docket number, then by bulletin
        by_docket = {}
        for a in keyword_alerts:
            dn = a['docket_number']
            if dn not in by_docket:
                by_docket[dn] = []
            by_docket[dn].append(a)

        for docket_num, items in sorted(by_docket.items()):
            portal_link = _docket_portal_link(docket_num)
            # Collect all matched keywords across items for this docket
            all_matched = []
            for item in items:
                for kw in item.get('matched_keywords', []):
                    if kw not in all_matched:
                        all_matched.append(kw)
            keywords_str = ", ".join(html_mod.escape(k) for k in all_matched)

            html_parts.append(f"""
    <div style="margin-bottom: 16px; padding: 12px; background: #f7fafc; border-radius: 6px; border: 1px solid #e2e8f0;">
      <strong style="color: #333; font-size: 14px;">{html_mod.escape(docket_num)}</strong>
      <span style="font-size: 12px; color: #718096;"> &mdash; Matched: {keywords_str}</span>
      <br>
      <a href="{portal_link}" style="font-size: 12px; color: #2b6cb0; text-decoration: none;">
        View docket on LPSC website &rarr;</a>
""")
            # Group by bulletin number within this docket
            by_bulletin = {}
            for item in items:
                bn = item.get('bulletin_number', 0)
                if bn not in by_bulletin:
                    by_bulletin[bn] = []
                by_bulletin[bn].append(item)

            for bulletin_num, bulletin_items in sorted(by_bulletin.items()):
                html_parts.append(f"""
      <div style="margin: 8px 0 4px 8px; font-size: 13px; color: #4a5568; font-weight: 600;">
        Bulletin #{bulletin_num}
      </div>
      <ul style="list-style: none; padding: 0; margin: 0 0 0 8px;">
""")
                for item in bulletin_items:
                    subpart_label = ""
                    if item.get('subpart'):
                        section_name = SUBPART_SECTIONS.get(item['subpart'], '')
                        subpart_label = f"Section {item['subpart']}"
                        if section_name:
                            subpart_label += f": {section_name}"
                        subpart_label = f' <span style="font-size: 11px; color: #a0aec0;">({subpart_label})</span>'

                    html_parts.append(f"""
        <li style="padding: 4px 0; font-size: 13px; color: #333;">
          {html_mod.escape(item['title'][:150])}{subpart_label}
        </li>
""")
                html_parts.append("      </ul>")

            html_parts.append("    </div>")

    # --- Docket Updates ---
    if docket_alerts:
        html_parts.append("""
    <h3 style="color: #2b6cb0; font-size: 15px; margin: 20px 0 10px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px;">
      Updates on Your Tracked Dockets
    </h3>
""")
        html_parts.extend(_render_docket_updates(docket_alerts))

    # --- Footer ---
    html_parts.append("""
  </div>
  <p style="text-align: center; font-size: 11px; color: #a0aec0; margin-top: 16px;">
    Sent by LPSC Alerts</p>
</div>
""")

    return {
        'subject': subject,
        'html': ''.join(html_parts),
        'recipient': recipient,
    }


def generate_user_notification_email(user: Dict, dockets: List[str],
                                      recent_docs: List[Dict],
                                      is_new_user: bool,
                                      docket_urls: Dict = None,
                                      keyword_docs: List[Dict] = None) -> Dict:
    """
    Build an HTML notification email for a user who was just added or updated.

    Args:
        user: Dict with 'email', 'include_keywords', 'exclude_keywords'
        dockets: List of tracked docket number strings
        recent_docs: List of alert-style dicts (same format as docket_monitor),
                     filtered to the most recent filing date per docket
        is_new_user: True for welcome email, False for settings-updated email
        docket_urls: Optional dict mapping docket number → DocketDetails URL
        keyword_docs: Optional list of alert-style dicts for keyword-matched
                      dockets from the latest bulletin. Each dict has the same
                      fields as recent_docs plus 'matched_keywords' (list of str).

    Returns:
        Dict with 'subject', 'html', 'recipient'
    """
    if docket_urls is None:
        docket_urls = {}
    if keyword_docs is None:
        keyword_docs = []
    if is_new_user:
        subject = "You have been added to LPSC Alerts"
        header_text = "Welcome to LPSC Alerts"
    else:
        subject = "Your settings have been updated on LPSC Alerts"
        header_text = "Your Settings Have Been Updated"

    html_parts = []

    # --- Header (matches existing blue banner style) ---
    html_parts.append(f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 640px; margin: 0 auto; padding: 20px;">
  <div style="background-color: #2b6cb0; color: white; padding: 16px 20px;
              border-radius: 8px 8px 0 0;">
    <h2 style="margin: 0; font-size: 18px;">{header_text}</h2>
    <p style="margin: 4px 0 0; font-size: 13px; opacity: 0.85;">
      Louisiana Public Service Commission</p>
  </div>
  <div style="padding: 20px; border: 1px solid #e2e8f0; border-top: none;
              border-radius: 0 0 8px 8px;">
""")

    # --- Your Settings section ---
    html_parts.append("""
    <h3 style="color: #2b6cb0; font-size: 15px; margin: 20px 0 10px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px;">
      Your Settings
    </h3>
    <div style="padding: 12px; background: #f7fafc; border-radius: 6px; border: 1px solid #e2e8f0; font-size: 13px; color: #333;">
""")

    # Keywords
    include_kw = user.get('include_keywords', '') or ''
    if include_kw:
        html_parts.append(f"""
      <p style="margin: 0 0 8px;"><strong>Keywords:</strong> {html_mod.escape(include_kw)}</p>
""")
    else:
        html_parts.append("""
      <p style="margin: 0 0 8px;"><strong>Keywords:</strong> <em style="color: #a0aec0;">None set</em></p>
""")

    # Exclusions
    exclude_kw = user.get('exclude_keywords', '') or ''
    if exclude_kw:
        html_parts.append(f"""
      <p style="margin: 0 0 8px;"><strong>Exclusions:</strong> {html_mod.escape(exclude_kw)}</p>
""")
    else:
        html_parts.append("""
      <p style="margin: 0 0 8px;"><strong>Exclusions:</strong> <em style="color: #a0aec0;">None set</em></p>
""")

    # Tracked dockets
    if dockets:
        docket_links = []
        for d in dockets:
            link = docket_urls.get(d, _docket_portal_link(d))
            docket_links.append(f'<a href="{link}" style="color: #2b6cb0; text-decoration: none;">{html_mod.escape(d)}</a>')
        html_parts.append(f"""
      <p style="margin: 0;"><strong>Tracked Dockets:</strong> {", ".join(docket_links)}</p>
""")
    else:
        html_parts.append("""
      <p style="margin: 0;"><strong>Tracked Dockets:</strong> <em style="color: #a0aec0;">None set</em></p>
""")

    html_parts.append("    </div>")

    # --- Keyword Matches from Latest Bulletin ---
    include_kw = user.get('include_keywords', '') or ''
    if include_kw:
        html_parts.append("""
    <h3 style="color: #2b6cb0; font-size: 15px; margin: 20px 0 10px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px;">
      Keyword Matches from Latest Bulletin
    </h3>
""")
        if keyword_docs:
            # Group by docket, show matched keywords, then render docs
            by_docket = {}
            for doc in keyword_docs:
                dn = doc['docket_number']
                if dn not in by_docket:
                    by_docket[dn] = {'keywords': set(), 'docs': []}
                by_docket[dn]['docs'].append(doc)
                for kw in doc.get('matched_keywords', []):
                    by_docket[dn]['keywords'].add(kw)

            for docket_num, info in sorted(by_docket.items()):
                keywords_str = ", ".join(html_mod.escape(k) for k in sorted(info['keywords']))
                docket_url = info['docs'][0].get('docket_url', '') if info['docs'] else ''
                portal_link = docket_url or _docket_portal_link(docket_num)

                html_parts.append(f"""
    <div style="margin-bottom: 16px; padding: 12px; background: #f7fafc; border-radius: 6px; border: 1px solid #e2e8f0;">
      <strong style="color: #333; font-size: 14px;">{html_mod.escape(docket_num)}</strong>
      <span style="font-size: 12px; color: #718096;"> &mdash; Matched: {keywords_str}</span>
      <br>
      <a href="{portal_link}" style="font-size: 12px; color: #2b6cb0; text-decoration: none;">
        View docket on LPSC website &rarr;</a>
""")
                # Group docs by filing date within this docket (parsed so we
                # can sort correctly and show a readable label).
                by_date = {}
                for doc in info['docs']:
                    d = _parse_filing_date(doc.get('date_filed'))
                    by_date.setdefault(d, []).append(doc)

                for d in sorted(by_date.keys(), key=lambda x: x or date.min, reverse=True):
                    date_items = by_date[d]
                    date_label = f"{d:%B} {d.day}, {d.year}" if d else "Date unknown"
                    html_parts.append(f"""
      <div style="margin: 8px 0 4px 8px; font-size: 13px; color: #4a5568; font-weight: 600;">
        {html_mod.escape(date_label)}
      </div>
      <ul style="list-style: none; padding: 0; margin: 0 0 0 8px;">
""")
                    for item in date_items:
                        desc = item.get('document_description', 'New filing')
                        details_url = item.get('details_url', '')
                        doc_type = item.get('document_type', '')
                        type_label = f' <span style="font-size: 11px; color: #a0aec0;">({html_mod.escape(doc_type)})</span>' if doc_type else ''
                        html_parts.append(f"""
        <li style="padding: 4px 0; font-size: 13px; color: #333;">
          <a href="{details_url}" style="color: #2b6cb0; text-decoration: none;">
            {html_mod.escape(desc[:150])}</a>{type_label}
        </li>
""")
                    html_parts.append("      </ul>")
                html_parts.append("    </div>")
        else:
            html_parts.append("""
    <p style="font-size: 13px; color: #718096;">
      No keyword matches found in the latest bulletin.</p>
""")

    # --- Recent Activity section ---
    html_parts.append("""
    <h3 style="color: #2b6cb0; font-size: 15px; margin: 20px 0 10px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px;">
      Recent Activity
    </h3>
""")

    if not dockets:
        html_parts.append("""
    <p style="font-size: 13px; color: #718096;">
      You don't have any tracked dockets. Add dockets to see recent filings here.</p>
""")
    elif not recent_docs:
        html_parts.append("""
    <p style="font-size: 13px; color: #718096;">
      No recent filings found for your tracked dockets in the last 30 days.</p>
""")
    else:
        html_parts.extend(_render_docket_updates(recent_docs))

    # --- Footer ---
    html_parts.append("""
  </div>
  <p style="text-align: center; font-size: 11px; color: #a0aec0; margin-top: 16px;">
    Sent by LPSC Alerts</p>
</div>
""")

    return {
        'subject': subject,
        'html': ''.join(html_parts),
        'recipient': user['email'],
    }


def generate_user_removal_email(email: str) -> Dict:
    """
    Build an HTML email notifying a user they have been removed from LPSC Alerts.

    Args:
        email: The user's email address

    Returns:
        Dict with 'subject', 'html', 'recipient'
    """
    html = """
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 640px; margin: 0 auto; padding: 20px;">
  <div style="background-color: #2b6cb0; color: white; padding: 16px 20px;
              border-radius: 8px 8px 0 0;">
    <h2 style="margin: 0; font-size: 18px;">You Have Been Removed from LPSC Alerts</h2>
    <p style="margin: 4px 0 0; font-size: 13px; opacity: 0.85;">
      Louisiana Public Service Commission</p>
  </div>
  <div style="padding: 20px; border: 1px solid #e2e8f0; border-top: none;
              border-radius: 0 0 8px 8px;">
    <p style="font-size: 14px; color: #333; margin: 0 0 12px;">
      Your account has been removed from LPSC Alerts. You will no longer
      receive notifications about LPSC docket activity.</p>
    <p style="font-size: 13px; color: #718096; margin: 0;">
      If you believe this was a mistake, please contact your administrator
      to be re-added.</p>
  </div>
  <p style="text-align: center; font-size: 11px; color: #a0aec0; margin-top: 16px;">
    Sent by LPSC Alerts</p>
</div>
"""
    return {
        'subject': 'You have been removed from LPSC Alerts',
        'html': html,
        'recipient': email,
    }
