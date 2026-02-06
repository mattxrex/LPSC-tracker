"""
PDF Parser for LPSC Bulletins

This module handles:
1. Extracting text from bulletin PDFs using pdfplumber
2. Identifying the Part II (Utilities) section
3. Parsing individual docket entries from the text

pdfplumber is a Python library that extracts text while preserving
the layout and structure of the PDF as much as possible.
"""

import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber not installed. Run: pip install pdfplumber")
    raise

from config import (
    DOCKET_PATTERN, PART_II_MARKERS, RELEVANT_DOCKET_TYPES,
    SUBPART_SECTIONS, log
)


@dataclass
class DocketEntry:
    """
    Represents a single docket entry extracted from a bulletin.

    Using a dataclass gives us a clean structure with automatic
    __repr__ for debugging and easy conversion to dict.
    """
    docket_number: str      # e.g., "U-37800" or "GENERAL-06-18-2025"
    docket_type: str        # e.g., "U", "GENERAL", "SPECIAL"
    title: str              # Full title/description text
    raw_text: str           # Original text block from PDF
    order_date: Optional[str] = None  # For ORDER entries
    order_number: Optional[str] = None  # e.g., "GENERAL ORDER NO. 06-18-2025"
    related_docket: Optional[str] = None  # For GENERAL ORDERs that reference a docket
    subpart: Optional[str] = None  # Section letter (A-J) from bulletin

    def to_dict(self) -> Dict:
        """Convert to dictionary for database storage."""
        return {
            'docket_number': self.docket_number,
            'docket_type': self.docket_type,
            'title': self.title,
            'description': self.raw_text,
            'order_date': self.order_date,
            'related_docket': self.related_docket,
            'subpart': self.subpart,
        }


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract all text from a PDF file.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Full text content of the PDF

    This function opens the PDF and extracts text from each page,
    joining them together. pdfplumber does a good job preserving
    the reading order and layout.
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    log(f"Extracting text from: {pdf_path}")

    full_text = []

    with pdfplumber.open(pdf_path) as pdf:
        log(f"PDF has {len(pdf.pages)} pages")

        for i, page in enumerate(pdf.pages):
            page_text = page.extract_text()
            if page_text:
                full_text.append(page_text)
                log(f"Page {i+1}: extracted {len(page_text)} characters")
            else:
                log(f"Page {i+1}: no text extracted (might be image-based)")

    combined_text = "\n\n".join(full_text)
    log(f"Total extracted: {len(combined_text)} characters")

    return combined_text


def find_part_ii_section(text: str) -> Tuple[int, int]:
    """
    Find the start and end positions of Part II (Utilities) section.

    The bulletin is divided into:
    - Part I: Transportation
    - Part II: Utilities (this is what we want)

    Args:
        text: Full bulletin text

    Returns:
        Tuple of (start_position, end_position) for Part II section
    """
    # Look for Part II marker
    part_ii_start = -1

    for marker in PART_II_MARKERS:
        pos = text.find(marker)
        if pos != -1:
            part_ii_start = pos
            log(f"Found Part II marker '{marker}' at position {pos}")
            break

    if part_ii_start == -1:
        # If no Part II marker found, might be a different format
        # Return the whole document as a fallback
        log("WARNING: Part II section not found, using full text")
        return (0, len(text))

    # Part II typically ends at the end of the document or at a
    # signature/footer section. Look for common end markers.
    end_markers = [
        "LPSC SECRETARY",
        "Secretary",
        "###",
        "END OF BULLETIN",
    ]

    part_ii_end = len(text)
    for marker in end_markers:
        # Look for marker AFTER Part II starts
        pos = text.find(marker, part_ii_start + 100)
        if pos != -1 and pos < part_ii_end:
            part_ii_end = pos
            log(f"Found end marker '{marker}' at position {pos}")

    return (part_ii_start, part_ii_end)


def _detect_subparts(text: str) -> List[Dict]:
    """
    Detect subpart section headers and their positions in the text.

    Bulletin Part II has sections like:
        A. RATE APPLICATIONS - N/A
        C. REQUESTS FOR AUTHORITY
        J. ORDERS

    Returns a list of dicts: [{'letter': 'A', 'pos': 123, 'is_na': True}, ...]
    sorted by position.
    """
    # Match patterns like "A. RATE APPLICATIONS" or "H. SECTION 301 M."
    # The letter must be A-J (valid Part II subparts) and followed by period + uppercase text
    pattern = re.compile(r'^([A-J])\.\s+([A-Z][A-Z \.0-9]+)', re.MULTILINE)

    subparts = []
    for match in pattern.finditer(text):
        letter = match.group(1)
        header_text = match.group(0)

        # Check if this section is marked N/A
        # Look at the rest of the line after the match
        line_end = text.find('\n', match.end())
        rest_of_line = text[match.end():line_end] if line_end > 0 else text[match.end():]
        is_na = 'N/A' in rest_of_line or 'N/A' in header_text

        subparts.append({
            'letter': letter,
            'pos': match.start(),
            'is_na': is_na,
        })
        log(f"Found subpart header: {letter}. (N/A={is_na}) at pos {match.start()}")

    return subparts


def _get_subpart_at_position(subparts: List[Dict], pos: int) -> Optional[str]:
    """
    Given a list of subpart headers and a position in the text,
    return the letter of the most recent subpart before that position.
    """
    current = None
    for sp in subparts:
        if sp['pos'] <= pos:
            current = sp['letter']
        else:
            break
    return current


def parse_docket_entries(text: str) -> List[DocketEntry]:
    """
    Parse individual docket entries from bulletin text.

    LPSC bulletins have entries in formats like:

    DOCKET NO. U-37800 - Entergy Louisiana, LLC, ex parte. In re:
    Application for approval to construct Votaw and Segno solar facilities...

    ORDER NO. U-37441 - 6/18/2025 - 1803 Electric Cooperative, Inc., ex parte...

    GENERAL ORDER NO. 06-18-2025 (R-35462) - 6/18/2025 - Description...

    SPECIAL ORDER NO. 30-2025 - 6/18/2025 - Description...

    This function uses regex patterns to identify and extract these entries.
    Each entry is assigned to the bulletin subpart (A-J) it appears under.
    """
    entries = []

    # Detect subpart section headers (A through J) and their positions
    subparts = _detect_subparts(text)

    # Common lookahead pattern for entry boundaries
    # Stops at: next docket/order entry, section headers (A. RATE..., B. CITATIONS...), or end
    # Section headers follow pattern: single uppercase letter + period + space + UPPERCASE words
    # Use (?-i:...) to make section header matching case-SENSITIVE (not affected by IGNORECASE flag)
    # This prevents matching things like "e. In" in "ex parte. In re:"
    boundary_lookahead = r'(?=(?:DOCKET\s+NO\.|(?:GENERAL\s+)?ORDER\s+NO\.|SPECIAL\s+ORDER\s+NO\.|(?-i:[A-Z]\.\s+[A-Z]{2,})|Page\s+\d|$))'

    # Pattern for DOCKET NO. entries
    # Matches: DOCKET NO. U-12345 - followed by title text
    docket_pattern = re.compile(
        r'DOCKET\s+NO\.\s+([URISXT])-(\d+)\s*[-–—]\s*(.+?)' + boundary_lookahead,
        re.IGNORECASE | re.DOTALL
    )

    # Pattern for ORDER NO. entries (standard docket orders)
    # Matches: ORDER NO. U-12345 - date - followed by title text
    order_pattern = re.compile(
        r'(?<!GENERAL\s)(?<!SPECIAL\s)ORDER\s+NO\.\s+([URISXT])-(\d+)\s*[-–—]\s*(\d{1,2}/\d{1,2}/\d{4})?\s*[-–—]?\s*(.+?)' + boundary_lookahead,
        re.IGNORECASE | re.DOTALL
    )

    # Pattern for GENERAL ORDER entries
    # Matches: GENERAL ORDER NO. 06-18-2025 (R-35462) - date - text
    # The (R-35462) part references the related docket
    general_order_pattern = re.compile(
        r'GENERAL\s+ORDER\s+NO\.\s+(\d{2}-\d{2}-\d{4})\s*\(([URISXT])-(\d+)\)\s*[-–—]\s*(\d{1,2}/\d{1,2}/\d{4})?\s*[-–—]?\s*(.+?)' + boundary_lookahead,
        re.IGNORECASE | re.DOTALL
    )

    # Pattern for SPECIAL ORDER entries
    # Matches: SPECIAL ORDER NO. 30-2025 - date - text
    special_order_pattern = re.compile(
        r'SPECIAL\s+ORDER\s+NO\.\s+(\d+-\d{4})\s*[-–—]\s*(\d{1,2}/\d{1,2}/\d{4})?\s*[-–—]?\s*(.+?)' + boundary_lookahead,
        re.IGNORECASE | re.DOTALL
    )

    # Find all DOCKET entries
    for match in docket_pattern.finditer(text):
        docket_type = match.group(1).upper()
        docket_num = match.group(2)
        title_text = match.group(3).strip()

        # Clean up the title (remove extra whitespace, newlines)
        title_text = ' '.join(title_text.split())

        entry = DocketEntry(
            docket_number=f"{docket_type}-{docket_num}",
            docket_type=docket_type,
            title=title_text,
            raw_text=match.group(0).strip(),
            subpart=_get_subpart_at_position(subparts, match.start()),
        )
        entries.append(entry)
        log(f"Found DOCKET: {entry.docket_number} (subpart: {entry.subpart})")

    # Find all standard ORDER entries (ORDER NO. U-xxxxx format)
    for match in order_pattern.finditer(text):
        docket_type = match.group(1).upper()
        docket_num = match.group(2)
        order_date = match.group(3)  # May be None
        title_text = match.group(4).strip()

        # Clean up the title
        title_text = ' '.join(title_text.split())

        entry = DocketEntry(
            docket_number=f"{docket_type}-{docket_num}",
            docket_type=docket_type,
            title=title_text,
            raw_text=match.group(0).strip(),
            order_date=order_date,
            subpart=_get_subpart_at_position(subparts, match.start()),
        )
        entries.append(entry)
        log(f"Found ORDER: {entry.docket_number} (date: {order_date}, subpart: {entry.subpart})")

    # Find all GENERAL ORDER entries
    for match in general_order_pattern.finditer(text):
        order_num = match.group(1)  # e.g., "06-18-2025"
        related_type = match.group(2).upper()  # e.g., "R"
        related_num = match.group(3)  # e.g., "35462"
        order_date = match.group(4)  # May be None
        title_text = match.group(5).strip()

        # Clean up the title
        title_text = ' '.join(title_text.split())

        # Use related docket as the docket_number for filtering purposes
        related_docket = f"{related_type}-{related_num}"

        entry = DocketEntry(
            docket_number=related_docket,  # Use related docket for filtering
            docket_type=related_type,
            title=title_text,
            raw_text=match.group(0).strip(),
            order_date=order_date,
            order_number=f"GENERAL ORDER NO. {order_num}",
            related_docket=related_docket,
            subpart=_get_subpart_at_position(subparts, match.start()),
        )
        entries.append(entry)
        log(f"Found GENERAL ORDER: {order_num} (related: {related_docket}, subpart: {entry.subpart})")

    # Find all SPECIAL ORDER entries
    for match in special_order_pattern.finditer(text):
        order_num = match.group(1)  # e.g., "30-2025"
        order_date = match.group(2)  # May be None
        title_text = match.group(3).strip()

        # Clean up the title
        title_text = ' '.join(title_text.split())

        # SPECIAL ORDERs don't have a docket reference, use order number as ID
        entry = DocketEntry(
            docket_number=f"SPECIAL-{order_num}",
            docket_type="SPECIAL",
            title=title_text,
            raw_text=match.group(0).strip(),
            order_date=order_date,
            order_number=f"SPECIAL ORDER NO. {order_num}",
            subpart=_get_subpart_at_position(subparts, match.start()),
        )
        entries.append(entry)
        log(f"Found SPECIAL ORDER: {order_num} (subpart: {entry.subpart})")

    # Remove duplicates (same docket might appear multiple times)
    seen = set()
    unique_entries = []
    for entry in entries:
        key = (entry.docket_number, entry.title[:50])  # Use first 50 chars of title
        if key not in seen:
            seen.add(key)
            unique_entries.append(entry)

    log(f"Parsed {len(unique_entries)} unique docket entries")
    return unique_entries


def filter_utility_dockets(entries: List[DocketEntry]) -> List[DocketEntry]:
    """
    Filter entries to only include relevant docket types.

    We want U, R, I, S, X dockets (utilities, rulemakings, IRPs, etc.)
    but NOT T (transportation) dockets.
    """
    filtered = [e for e in entries if e.docket_type in RELEVANT_DOCKET_TYPES]
    log(f"Filtered to {len(filtered)} utility-related dockets")
    return filtered


def extract_bulletin_date(text: str) -> Optional[str]:
    """
    Extract the bulletin date from the PDF text.

    Bulletins have a consistent header format:
        OFFICIAL BULLETIN #1368 January 30, 2026

    Args:
        text: Full text extracted from the bulletin PDF

    Returns:
        Date string in YYYY-MM-DD format, or None if not found.
    """
    match = re.search(
        r'OFFICIAL\s+BULLETIN\s+#\d+\s+(\w+\s+\d{1,2},?\s+\d{4})', text
    )
    if not match:
        log("WARNING: Could not find bulletin date in PDF text")
        return None

    date_str = match.group(1)
    try:
        from datetime import datetime
        parsed = datetime.strptime(date_str, "%B %d, %Y")
        result = parsed.strftime("%Y-%m-%d")
        log(f"Extracted bulletin date: {result}")
        return result
    except ValueError:
        log(f"WARNING: Could not parse bulletin date: {date_str}")
        return None


def extract_next_bulletin_date(text: str) -> Optional[str]:
    """
    Extract the next bulletin's mailing date from the PDF text.

    Bulletins contain text like:
        "PRIOR TO MAILING ON FRIDAY, FEBRUARY 13, 2026"

    This is the date the NEXT bulletin will be mailed/published.

    Args:
        text: Full text extracted from the bulletin PDF

    Returns:
        Date string in YYYY-MM-DD format, or None if not found.
    """
    match = re.search(
        r'MAILING\s+ON\s+\w+,\s+(\w+\s+\d{1,2},?\s+\d{4})', text
    )
    if not match:
        log("WARNING: Could not find next bulletin mailing date in PDF text")
        return None

    date_str = match.group(1)
    try:
        from datetime import datetime
        parsed = datetime.strptime(date_str, "%B %d, %Y")
        result = parsed.strftime("%Y-%m-%d")
        log(f"Extracted next bulletin date: {result}")
        return result
    except ValueError:
        log(f"WARNING: Could not parse next bulletin date: {date_str}")
        return None


def parse_bulletin(pdf_path: str) -> List[DocketEntry]:
    """
    Main function to parse a bulletin PDF and extract docket entries.

    This is the primary entry point for parsing. It:
    1. Extracts text from the PDF
    2. Finds the Part II (Utilities) section
    3. Parses docket entries from that section
    4. Filters for relevant docket types

    Args:
        pdf_path: Path to the bulletin PDF

    Returns:
        List of DocketEntry objects for relevant dockets
    """
    # Step 1: Extract text
    full_text = extract_text_from_pdf(pdf_path)

    # Step 2: Find Part II section
    start, end = find_part_ii_section(full_text)
    part_ii_text = full_text[start:end]
    log(f"Part II section: {len(part_ii_text)} characters")

    # Step 3: Parse docket entries
    entries = parse_docket_entries(part_ii_text)

    # Step 4: Filter for utility dockets
    utility_entries = filter_utility_dockets(entries)

    return utility_entries


# =============================================================================
# TESTING / CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python bulletin_parser.py <pdf_path>")
        print("\nThis will extract and display all docket entries from the PDF.")
        sys.exit(1)

    pdf_path = sys.argv[1]

    print(f"\nParsing bulletin: {pdf_path}")
    print("=" * 60)

    try:
        entries = parse_bulletin(pdf_path)

        print(f"\nFound {len(entries)} relevant docket entries:\n")

        for i, entry in enumerate(entries, 1):
            print(f"{i}. {entry.docket_number}")
            print(f"   Type: {entry.docket_type}")
            print(f"   Subpart: {entry.subpart}")
            print(f"   Title: {entry.title[:100]}...")
            if entry.order_date:
                print(f"   Order Date: {entry.order_date}")
            print()

    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR parsing PDF: {e}")
        raise
