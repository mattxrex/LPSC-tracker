"""
Keyword Filtering and Relevance Scoring for LPSC Dockets

This module determines which dockets are relevant to electric utilities
by analyzing the docket title and description against keyword lists.

How scoring works:
- Each high-priority keyword match = +10 points
- Each medium-priority keyword match = +3 points
- Exclusion keywords (gas, water, telecom) = -15 points
- A docket is "relevant" if score >= threshold (default 5)
"""

import re
from typing import List, Tuple, Set
from dataclasses import dataclass

from config import (
    HIGH_PRIORITY_KEYWORDS,
    MEDIUM_PRIORITY_KEYWORDS,
    EXCLUSION_KEYWORDS,
    HIGH_PRIORITY_SCORE,
    MEDIUM_PRIORITY_SCORE,
    EXCLUSION_PENALTY,
    RELEVANCE_THRESHOLD,
    log
)


@dataclass
class FilterResult:
    """
    Result of filtering a single docket.

    Contains the relevance determination, score, and which keywords matched.
    """
    is_relevant: bool
    priority_score: int
    high_priority_matches: List[str]
    medium_priority_matches: List[str]
    exclusion_matches: List[str]

    @property
    def all_matches(self) -> List[str]:
        """All positive keywords that matched."""
        return self.high_priority_matches + self.medium_priority_matches

    def __repr__(self):
        status = "RELEVANT" if self.is_relevant else "not relevant"
        return f"FilterResult({status}, score={self.priority_score}, matches={self.all_matches})"


def find_keyword_matches(text: str, keywords: List[str]) -> List[str]:
    """
    Find which keywords appear in the text.

    Args:
        text: The text to search in
        keywords: List of keywords to look for

    Returns:
        List of keywords that were found (case-insensitive matching)
    """
    text_lower = text.lower()
    matches = []

    for keyword in keywords:
        # Use word boundary matching to avoid partial matches
        # e.g., "solar" shouldn't match "insolar"
        pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
        if re.search(pattern, text_lower):
            matches.append(keyword)

    return matches


def calculate_relevance(title: str, description: str = None) -> FilterResult:
    """
    Calculate the relevance score for a docket.

    This is the main filtering function. It checks the docket's title
    and description against our keyword lists and calculates a score.

    Args:
        title: The docket title from the bulletin
        description: Additional description text (optional)

    Returns:
        FilterResult with relevance determination and matched keywords
    """
    # Combine title and description for searching
    full_text = title
    if description:
        full_text += " " + description

    # Find matches in each category
    high_matches = find_keyword_matches(full_text, HIGH_PRIORITY_KEYWORDS)
    medium_matches = find_keyword_matches(full_text, MEDIUM_PRIORITY_KEYWORDS)
    exclusion_matches = find_keyword_matches(full_text, EXCLUSION_KEYWORDS)

    # Calculate score
    score = 0
    score += len(high_matches) * HIGH_PRIORITY_SCORE
    score += len(medium_matches) * MEDIUM_PRIORITY_SCORE
    score += len(exclusion_matches) * EXCLUSION_PENALTY

    # Determine relevance
    is_relevant = score >= RELEVANCE_THRESHOLD

    result = FilterResult(
        is_relevant=is_relevant,
        priority_score=score,
        high_priority_matches=high_matches,
        medium_priority_matches=medium_matches,
        exclusion_matches=exclusion_matches
    )

    log(f"Filter result: score={score}, relevant={is_relevant}, "
        f"high={high_matches}, medium={medium_matches}, exclude={exclusion_matches}")

    return result


def filter_docket_entries(entries: List) -> List[Tuple]:
    """
    Filter a list of docket entries and return results.

    Args:
        entries: List of DocketEntry objects from bulletin_parser

    Returns:
        List of tuples: (DocketEntry, FilterResult)
    """
    results = []

    for entry in entries:
        filter_result = calculate_relevance(entry.title, entry.raw_text)
        results.append((entry, filter_result))

    # Sort by relevance score (highest first)
    results.sort(key=lambda x: x[1].priority_score, reverse=True)

    # Log summary
    relevant_count = sum(1 for _, fr in results if fr.is_relevant)
    log(f"Filtered {len(entries)} entries: {relevant_count} relevant")

    return results


def get_relevant_only(entries: List) -> List[Tuple]:
    """
    Filter entries and return only the relevant ones.

    Args:
        entries: List of DocketEntry objects

    Returns:
        List of (DocketEntry, FilterResult) tuples for relevant dockets only
    """
    all_results = filter_docket_entries(entries)
    return [(entry, result) for entry, result in all_results if result.is_relevant]


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def explain_relevance(title: str, description: str = None) -> str:
    """
    Generate a human-readable explanation of why a docket is/isn't relevant.

    Useful for debugging and understanding filter decisions.
    """
    result = calculate_relevance(title, description)

    lines = []
    lines.append(f"Relevance: {'YES' if result.is_relevant else 'NO'}")
    lines.append(f"Score: {result.priority_score} (threshold: {RELEVANCE_THRESHOLD})")

    if result.high_priority_matches:
        lines.append(f"High-priority keywords: {', '.join(result.high_priority_matches)}")

    if result.medium_priority_matches:
        lines.append(f"Medium-priority keywords: {', '.join(result.medium_priority_matches)}")

    if result.exclusion_matches:
        lines.append(f"Exclusion keywords (penalty): {', '.join(result.exclusion_matches)}")

    if not result.all_matches and not result.exclusion_matches:
        lines.append("No keywords matched")

    return "\n".join(lines)


# =============================================================================
# TESTING / CLI
# =============================================================================

if __name__ == "__main__":
    # Test the filter with some example docket titles
    test_cases = [
        "Entergy Louisiana, LLC, ex parte. In re: Application for approval to construct Votaw and Segno solar facilities",
        "Cleco Power LLC. In re: Request for approval of fuel adjustment clause",
        "Southwest Gas Corporation. In re: Application for natural gas pipeline extension",
        "ABC Telephone Company. In re: Telecommunications service area expansion",
        "SWEPCO. In re: Integrated Resource Plan filing and renewable energy additions",
        "City Water Utility. In re: Water rate increase application",
        "1803 Electric Cooperative, Inc. In re: Rural electric service reliability improvements",
    ]

    print("LPSC Docket Relevance Filter Test")
    print("=" * 60)

    for title in test_cases:
        print(f"\nTitle: {title[:60]}...")
        print("-" * 40)
        print(explain_relevance(title))
