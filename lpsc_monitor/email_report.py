"""
HTML Email Report Generator for LPSC Bulletin Monitor

This module generates an HTML-formatted email report organized by bulletin
subparts (A through J). Each section shows relevant dockets with their
scores, keywords, and any document summaries.

The HTML uses inline CSS for email client compatibility (most email clients
don't support <style> blocks).
"""

from typing import List, Dict, Optional

from config import SUBPART_SECTIONS, LPSC_BASE_URL, log
import database as db


# =============================================================================
# PORTAL LINK HELPERS
# =============================================================================

def _docket_search_link(docket_number: str) -> str:
    """
    Build a link to search for a docket on the LPSC portal.

    This is a best-effort link — the portal's document search page
    doesn't support direct docket URL linking, but this takes you to
    the search page where you can look it up.
    """
    return f"{LPSC_BASE_URL}/portal/PSC"


# =============================================================================
# HTML GENERATION
# =============================================================================

def _style(name: str) -> str:
    """
    Return inline CSS for common elements.

    We use inline styles because email clients (Gmail, Outlook, etc.)
    strip out <style> blocks. Keeping them in a helper function makes
    the HTML template code more readable.
    """
    styles = {
        'body': 'font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: #333; max-width: 800px; margin: 0 auto; padding: 20px;',
        'header': 'background-color: #1a365d; color: white; padding: 20px 24px; border-radius: 8px 8px 0 0;',
        'header_title': 'margin: 0; font-size: 22px; font-weight: 600;',
        'header_date': 'margin: 4px 0 0 0; font-size: 14px; opacity: 0.85;',
        'section': 'margin: 24px 0; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden;',
        'section_header': 'background-color: #edf2f7; padding: 12px 16px; font-size: 15px; font-weight: 600; color: #2d3748; border-bottom: 1px solid #e2e8f0;',
        'section_na': 'background-color: #f7fafc; padding: 12px 16px; font-size: 15px; color: #a0aec0; border-bottom: 1px solid #e2e8f0;',
        'docket': 'padding: 14px 16px; border-bottom: 1px solid #f0f0f0;',
        'docket_number': 'font-weight: 700; color: #2b6cb0; font-size: 15px;',
        'docket_score': 'display: inline-block; background-color: #ebf8ff; color: #2b6cb0; padding: 2px 8px; border-radius: 12px; font-size: 12px; margin-left: 8px;',
        'docket_title': 'margin: 6px 0 0 0; font-size: 13px; color: #4a5568; line-height: 1.4;',
        'keywords': 'margin: 4px 0 0 0; font-size: 12px; color: #718096;',
        'doc_summary': 'margin: 10px 0 4px 16px; padding: 10px 14px; background-color: #f7fafc; border-left: 3px solid #4299e1; font-size: 13px; line-height: 1.5; color: #4a5568;',
        'doc_link': 'font-size: 12px; color: #4299e1; text-decoration: none; margin-left: 16px;',
        'no_items': 'padding: 10px 16px; font-size: 13px; color: #a0aec0; font-style: italic;',
        'footer': 'margin-top: 24px; padding: 16px; text-align: center; font-size: 12px; color: #a0aec0;',
        'next_date': 'margin-top: 16px; padding: 12px 16px; background-color: #fffaf0; border: 1px solid #fbd38d; border-radius: 6px; font-size: 14px; color: #744210;',
    }
    return styles.get(name, '')


def generate_html_report(bulletin_number: int) -> Optional[str]:
    """
    Generate an HTML email report for a specific bulletin.

    The report is organized by subpart (A through J), showing:
    - Section headers with display names
    - Relevant dockets with scores and keyword matches
    - Document summaries with portal links
    - Sections marked N/A when they had no content in the bulletin

    Args:
        bulletin_number: The bulletin number to generate a report for

    Returns:
        HTML string ready to be sent as an email body, or None if bulletin not found
    """
    db.init_database()

    # Look up the bulletin
    bulletin = db.get_bulletin(bulletin_number)
    if not bulletin:
        print(f"ERROR: Bulletin #{bulletin_number} not found in database.")
        return None

    bulletin_id = bulletin['id']
    bulletin_date = bulletin.get('date', 'Unknown date')
    next_date = bulletin.get('next_bulletin_date')

    # Get ALL dockets for this bulletin (relevant and not), so we know
    # which subparts had content
    all_dockets = db.get_dockets_by_bulletin(bulletin_id)

    # Get relevant dockets with their documents
    relevant_dockets = db.get_relevant_dockets(bulletin_id)

    # Build lookup: subpart letter -> list of relevant dockets
    dockets_by_subpart = {}
    for docket in relevant_dockets:
        sp = docket.get('subpart') or '?'
        if sp not in dockets_by_subpart:
            dockets_by_subpart[sp] = []
        dockets_by_subpart[sp].append(docket)

    # Track which subparts had ANY dockets (relevant or not)
    subparts_with_content = set()
    for docket in all_dockets:
        sp = docket.get('subpart')
        if sp:
            subparts_with_content.add(sp)

    # Start building the HTML
    html_parts = []

    # Email wrapper
    html_parts.append(f'<div style="{_style("body")}">')

    # Header
    html_parts.append(f'<div style="{_style("header")}">')
    html_parts.append(f'  <h1 style="{_style("header_title")}">LPSC Bulletin #{bulletin_number}</h1>')
    html_parts.append(f'  <p style="{_style("header_date")}">Published {bulletin_date}</p>')
    html_parts.append('</div>')

    # Summary line with link to bulletin on LPSC website
    bulletin_url = bulletin.get('pdf_url', '')
    html_parts.append(f'<p style="padding: 12px 16px 0 16px; font-size: 14px; color: #4a5568;">')
    html_parts.append(f'  Found <strong>{len(relevant_dockets)}</strong> relevant docket(s) in this bulletin.')
    html_parts.append('</p>')
    if bulletin_url:
        html_parts.append(
            f'<p style="padding: 0 16px 12px 16px; margin-top: 4px;">'
            f'<a href="{bulletin_url}" style="color: #4299e1; text-decoration: none; font-size: 14px;">'
            f'View bulletin on LPSC website &rarr;</a></p>'
        )

    # Sections A through J
    for letter, display_name in SUBPART_SECTIONS.items():
        section_dockets = dockets_by_subpart.get(letter, [])
        has_content = letter in subparts_with_content

        html_parts.append(f'<div style="{_style("section")}">')

        # Section header
        if not has_content:
            # Section was N/A in the bulletin
            html_parts.append(
                f'<div style="{_style("section_na")}">'
                f'{letter}. {display_name} &mdash; N/A</div>'
            )
        else:
            html_parts.append(
                f'<div style="{_style("section_header")}">'
                f'{letter}. {display_name}</div>'
            )

        if has_content and not section_dockets:
            # Section had dockets but none were relevant
            html_parts.append(
                f'<div style="{_style("no_items")}">No relevant items in this section</div>'
            )
        elif section_dockets:
            # Show each relevant docket
            for docket in section_dockets:
                html_parts.append(_render_docket(docket))

        html_parts.append('</div>')

    # Show any dockets that don't have a subpart assigned (legacy data)
    unassigned = dockets_by_subpart.get('?', [])
    if unassigned:
        html_parts.append(f'<div style="{_style("section")}">')
        html_parts.append(
            f'<div style="{_style("section_header")}">Other Relevant Dockets</div>'
        )
        for docket in unassigned:
            html_parts.append(_render_docket(docket))
        html_parts.append('</div>')

    # Next bulletin date
    if next_date:
        html_parts.append(
            f'<div style="{_style("next_date")}">'
            f'Next bulletin expected: <strong>{next_date}</strong></div>'
        )

    # Footer
    html_parts.append(
        f'<div style="{_style("footer")}">'
        f'Generated by LPSC Bulletin Monitor</div>'
    )

    html_parts.append('</div>')

    return '\n'.join(html_parts)


def _render_docket(docket: Dict) -> str:
    """
    Render a single docket entry as an HTML block.

    Includes the docket number, score, title, keywords, and any
    document summaries with portal links.
    """
    parts = []
    parts.append(f'<div style="{_style("docket")}">')

    # Docket number and score
    parts.append(
        f'  <span style="{_style("docket_number")}">{docket["docket_number"]}</span>'
        f'  <span style="{_style("docket_score")}">{docket["priority_score"]} pts</span>'
    )

    # Title (truncate if very long)
    title = docket.get('title', '')
    if len(title) > 200:
        title = title[:200] + '...'
    parts.append(f'  <p style="{_style("docket_title")}">{title}</p>')

    # Keywords
    keywords = docket.get('keywords_matched', '')
    if keywords:
        parts.append(
            f'  <p style="{_style("keywords")}">Keywords: {keywords}</p>'
        )

    # Document summaries
    documents = db.get_documents_by_docket(docket['id'])
    for doc in documents:
        if doc.get('summary'):
            # Convert markdown-style bold to HTML bold in summaries
            summary_html = doc['summary'].replace('**', '<strong>', 1)
            while '**' in summary_html:
                summary_html = summary_html.replace('**', '</strong>', 1)
                if '**' in summary_html:
                    summary_html = summary_html.replace('**', '<strong>', 1)

            # Convert newlines to <br> for email
            summary_html = summary_html.replace('\n', '<br>')

            parts.append(f'  <div style="{_style("doc_summary")}">{summary_html}</div>')

        # Link to document on portal
        if doc.get('document_url'):
            doc_type = doc.get('document_type', 'Document')
            parts.append(
                f'  <a href="{doc["document_url"]}" style="{_style("doc_link")}">'
                f'View {doc_type} on LPSC Portal</a>'
            )

    parts.append('</div>')
    return '\n'.join(parts)
