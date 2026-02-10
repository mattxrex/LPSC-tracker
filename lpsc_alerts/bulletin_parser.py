"""
PDF Parser for LPSC Bulletins

Copied from lpsc_monitor with import paths adjusted for lpsc_alerts.

Handles:
1. Extracting text from bulletin PDFs using pdfplumber
2. Identifying the Part II (Utilities) section
3. Parsing individual docket entries from the text
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
    """
    docket_number: str
    docket_type: str
    title: str
    raw_text: str
    order_date: Optional[str] = None
    order_number: Optional[str] = None
    related_docket: Optional[str] = None
    subpart: Optional[str] = None

    def to_dict(self) -> Dict:
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
    """Extract all text from a PDF file."""
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
                log(f"Page {i+1}: no text extracted")

    combined_text = "\n\n".join(full_text)
    log(f"Total extracted: {len(combined_text)} characters")
    return combined_text


def find_part_ii_section(text: str) -> Tuple[int, int]:
    """Find the start and end positions of Part II (Utilities) section."""
    part_ii_start = -1
    for marker in PART_II_MARKERS:
        pos = text.find(marker)
        if pos != -1:
            part_ii_start = pos
            log(f"Found Part II marker '{marker}' at position {pos}")
            break

    if part_ii_start == -1:
        log("WARNING: Part II section not found, using full text")
        return (0, len(text))

    end_markers = ["LPSC SECRETARY", "Secretary", "###", "END OF BULLETIN"]
    part_ii_end = len(text)
    for marker in end_markers:
        pos = text.find(marker, part_ii_start + 100)
        if pos != -1 and pos < part_ii_end:
            part_ii_end = pos
            log(f"Found end marker '{marker}' at position {pos}")

    return (part_ii_start, part_ii_end)


def _detect_subparts(text: str) -> List[Dict]:
    """Detect subpart section headers and their positions in the text."""
    pattern = re.compile(r'^([A-J])\.\s+([A-Z][A-Z \.0-9]+)', re.MULTILINE)
    subparts = []
    for match in pattern.finditer(text):
        letter = match.group(1)
        header_text = match.group(0)
        line_end = text.find('\n', match.end())
        rest_of_line = text[match.end():line_end] if line_end > 0 else text[match.end():]
        is_na = 'N/A' in rest_of_line or 'N/A' in header_text
        subparts.append({'letter': letter, 'pos': match.start(), 'is_na': is_na})
        log(f"Found subpart header: {letter}. (N/A={is_na}) at pos {match.start()}")
    return subparts


def _get_subpart_at_position(subparts: List[Dict], pos: int) -> Optional[str]:
    """Return the letter of the most recent subpart before the given position."""
    current = None
    for sp in subparts:
        if sp['pos'] <= pos:
            current = sp['letter']
        else:
            break
    return current


def parse_docket_entries(text: str) -> List[DocketEntry]:
    """Parse individual docket entries from bulletin text."""
    entries = []
    subparts = _detect_subparts(text)

    boundary_lookahead = r'(?=(?:DOCKET\s+NO\.|(?:GENERAL\s+)?ORDER\s+NO\.|SPECIAL\s+ORDER\s+NO\.|(?-i:[A-Z]\.\s+[A-Z]{2,})|Page\s+\d|$))'

    docket_pattern = re.compile(
        r'DOCKET\s+NO\.\s+([URISXT])-(\d+)\s*[-–—]\s*(.+?)' + boundary_lookahead,
        re.IGNORECASE | re.DOTALL
    )
    order_pattern = re.compile(
        r'(?<!GENERAL\s)(?<!SPECIAL\s)ORDER\s+NO\.\s+([URISXT])-(\d+)\s*[-–—]\s*(\d{1,2}/\d{1,2}/\d{4})?\s*[-–—]?\s*(.+?)' + boundary_lookahead,
        re.IGNORECASE | re.DOTALL
    )
    general_order_pattern = re.compile(
        r'GENERAL\s+ORDER\s+NO\.\s+(\d{2}-\d{2}-\d{4})\s*\(([URISXT])-(\d+)\)\s*[-–—]\s*(\d{1,2}/\d{1,2}/\d{4})?\s*[-–—]?\s*(.+?)' + boundary_lookahead,
        re.IGNORECASE | re.DOTALL
    )
    special_order_pattern = re.compile(
        r'SPECIAL\s+ORDER\s+NO\.\s+(\d+-\d{4})\s*[-–—]\s*(\d{1,2}/\d{1,2}/\d{4})?\s*[-–—]?\s*(.+?)' + boundary_lookahead,
        re.IGNORECASE | re.DOTALL
    )

    # DOCKET entries
    for match in docket_pattern.finditer(text):
        docket_type = match.group(1).upper()
        docket_num = match.group(2)
        title_text = ' '.join(match.group(3).strip().split())
        entries.append(DocketEntry(
            docket_number=f"{docket_type}-{docket_num}",
            docket_type=docket_type,
            title=title_text,
            raw_text=match.group(0).strip(),
            subpart=_get_subpart_at_position(subparts, match.start()),
        ))

    # ORDER entries
    for match in order_pattern.finditer(text):
        docket_type = match.group(1).upper()
        docket_num = match.group(2)
        order_date = match.group(3)
        title_text = ' '.join(match.group(4).strip().split())
        entries.append(DocketEntry(
            docket_number=f"{docket_type}-{docket_num}",
            docket_type=docket_type,
            title=title_text,
            raw_text=match.group(0).strip(),
            order_date=order_date,
            subpart=_get_subpart_at_position(subparts, match.start()),
        ))

    # GENERAL ORDER entries
    for match in general_order_pattern.finditer(text):
        order_num = match.group(1)
        related_type = match.group(2).upper()
        related_num = match.group(3)
        order_date = match.group(4)
        title_text = ' '.join(match.group(5).strip().split())
        related_docket = f"{related_type}-{related_num}"
        entries.append(DocketEntry(
            docket_number=related_docket,
            docket_type=related_type,
            title=title_text,
            raw_text=match.group(0).strip(),
            order_date=order_date,
            order_number=f"GENERAL ORDER NO. {order_num}",
            related_docket=related_docket,
            subpart=_get_subpart_at_position(subparts, match.start()),
        ))

    # SPECIAL ORDER entries
    for match in special_order_pattern.finditer(text):
        order_num = match.group(1)
        order_date = match.group(2)
        title_text = ' '.join(match.group(3).strip().split())
        entries.append(DocketEntry(
            docket_number=f"SPECIAL-{order_num}",
            docket_type="SPECIAL",
            title=title_text,
            raw_text=match.group(0).strip(),
            order_date=order_date,
            order_number=f"SPECIAL ORDER NO. {order_num}",
            subpart=_get_subpart_at_position(subparts, match.start()),
        ))

    # Remove duplicates
    seen = set()
    unique_entries = []
    for entry in entries:
        key = (entry.docket_number, entry.title[:50])
        if key not in seen:
            seen.add(key)
            unique_entries.append(entry)

    log(f"Parsed {len(unique_entries)} unique docket entries")
    return unique_entries


def filter_utility_dockets(entries: List[DocketEntry]) -> List[DocketEntry]:
    """Filter entries to only include relevant docket types."""
    filtered = [e for e in entries if e.docket_type in RELEVANT_DOCKET_TYPES]
    log(f"Filtered to {len(filtered)} utility-related dockets")
    return filtered


def extract_bulletin_date(text: str) -> Optional[str]:
    """Extract the bulletin date from PDF text. Returns YYYY-MM-DD or None."""
    match = re.search(
        r'OFFICIAL\s+BULLETIN\s+#\d+\s+(\w+\s+\d{1,2},?\s+\d{4})', text
    )
    if not match:
        return None
    try:
        from datetime import datetime
        parsed = datetime.strptime(match.group(1), "%B %d, %Y")
        return parsed.strftime("%Y-%m-%d")
    except ValueError:
        return None


def parse_bulletin(pdf_path: str) -> List[DocketEntry]:
    """
    Parse a bulletin PDF and return relevant docket entries.

    Steps: extract text → find Part II → parse entries → filter
    """
    full_text = extract_text_from_pdf(pdf_path)
    start, end = find_part_ii_section(full_text)
    part_ii_text = full_text[start:end]
    entries = parse_docket_entries(part_ii_text)
    return filter_utility_dockets(entries)
