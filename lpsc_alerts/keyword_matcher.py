"""
Keyword Matcher for LPSC Alerts

Simple include/exclude matching logic:
1. If ANY exclude keyword matches → not relevant (exclusions win)
2. If ANY include keyword matches → relevant (return which matched)
3. Otherwise → not relevant

Uses case-insensitive word-boundary regex matching.
"""

import re
from typing import List, Optional, Tuple
from config import log


def _keyword_matches(keyword: str, text: str) -> bool:
    """
    Check if a keyword appears in text using word-boundary matching.

    Case-insensitive. Uses \\b word boundaries so "solar" matches
    "Solar energy" but not "insolar".
    """
    pattern = r'\b' + re.escape(keyword) + r'\b'
    return bool(re.search(pattern, text, re.IGNORECASE))


def match_keywords(text: str, include_keywords: str,
                   exclude_keywords: str = "") -> Tuple[bool, List[str]]:
    """
    Check if text matches a user's keyword preferences.

    Args:
        text: The docket title/description to match against
        include_keywords: Comma-separated include keywords
        exclude_keywords: Comma-separated exclude keywords

    Returns:
        Tuple of (is_relevant, matched_keywords)
        - is_relevant: True if text matches include and doesn't match exclude
        - matched_keywords: List of include keywords that matched
    """
    if not text or not include_keywords:
        return (False, [])

    # Parse keyword lists
    includes = [k.strip() for k in include_keywords.split(',') if k.strip()]
    excludes = [k.strip() for k in (exclude_keywords or '').split(',') if k.strip()]

    # Check exclusions first — any match means not relevant
    for kw in excludes:
        if _keyword_matches(kw, text):
            log(f"Excluded by '{kw}': {text[:60]}...")
            return (False, [])

    # Check include keywords
    matched = [kw for kw in includes if _keyword_matches(kw, text)]

    if matched:
        log(f"Matched {matched}: {text[:60]}...")
        return (True, matched)

    return (False, [])
