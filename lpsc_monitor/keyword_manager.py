"""
Custom keyword management for the LPSC Bulletin Monitor.

The built-in keyword lists live in config.py. User-added keywords are stored
separately in data/custom_keywords.json and merged into those lists at startup
(see config.py). This module powers the `keywords`, `add-keyword`, and
`remove-keyword` commands.

A keyword's "weight" is the tier it belongs to:
    high    -> +10 points
    medium  -> +3 points
    exclude -> -15 points (filters a docket out)
"""

import json

import config

# Accept a few friendly spellings for each tier; map them to the canonical name.
TIER_ALIASES = {
    "high": "high", "h": "high", "+10": "high",
    "medium": "medium", "med": "medium", "m": "medium", "+3": "medium",
    "exclude": "exclude", "exclusion": "exclude", "exc": "exclude",
    "x": "exclude", "-15": "exclude",
}

TIER_LABELS = {"high": "High priority", "medium": "Medium priority", "exclude": "Exclusion"}


def _points(tier):
    """Point value for a tier, read from config so the two never drift apart."""
    return config.KEYWORD_TIERS[tier][1]


def _load():
    """Load the custom-keyword file as {'high': [...], 'medium': [...], 'exclude': [...]}."""
    empty = {tier: [] for tier in config.KEYWORD_TIERS}
    try:
        with open(config.CUSTOM_KEYWORDS_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        return empty
    return {tier: list(data.get(tier, [])) for tier in config.KEYWORD_TIERS}


def _save(custom):
    config.CUSTOM_KEYWORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.CUSTOM_KEYWORDS_FILE, "w") as f:
        json.dump(custom, f, indent=2)


def _find_existing_tier(term):
    """Return the tier a term is already in (built-in or custom), or None."""
    term_l = term.lower()
    for tier, (kw_list, _pts) in config.KEYWORD_TIERS.items():
        if any(k.lower() == term_l for k in kw_list):
            return tier
    return None


def print_keywords():
    """Print all keyword tiers with their weights."""
    print("\nLPSC Monitor — Keywords")
    print("=" * 60)
    for tier in ("high", "medium", "exclude"):
        kw_list, pts = config.KEYWORD_TIERS[tier]
        print(f"\n{TIER_LABELS[tier]} ({pts:+d} points each) — {len(kw_list)} terms")
        for k in kw_list:
            print(f"    {k}")
    print(f"\nRelevance threshold: {config.RELEVANCE_THRESHOLD}+ points = relevant.\n")


def _split_terms(raw):
    """Split a comma-separated input into a clean list of individual terms."""
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def add_keyword(terms_input, tier_input):
    """
    Add one or more (comma-separated) custom keywords to a single tier.

    Returns True if at least one keyword was added.
    """
    tier = TIER_ALIASES.get((tier_input or "").strip().lower())
    if tier is None:
        print(f"ERROR: unknown weight '{tier_input}'. Use: high, medium, or exclude.")
        return False

    terms = _split_terms(terms_input)
    if not terms:
        print("ERROR: no keyword text provided.")
        return False

    # All keywords currently known (built-in + custom), case-insensitive.
    known = set()
    for _kw_list, _pts in config.KEYWORD_TIERS.values():
        known |= {k.lower() for k in _kw_list}

    custom = _load()
    added, skipped = [], []
    for term in terms:
        if term.lower() in known:
            skipped.append(term)
            continue
        custom[tier].append(term)
        known.add(term.lower())   # guard against duplicates within the same input
        added.append(term)

    if added:
        _save(custom)
        print(f"Added {len(added)} keyword(s) to {TIER_LABELS[tier]} "
              f"({_points(tier):+d} points): " + ", ".join(f"'{t}'" for t in added))
        print("They will be used on the next check.")
    if skipped:
        print(f"Skipped {len(skipped)} already-existing: "
              + ", ".join(f"'{t}'" for t in skipped))
    return bool(added)


def remove_keyword(terms_input):
    """
    Remove one or more (comma-separated) custom keywords.

    Built-in keywords can't be removed here. Returns True if at least one
    keyword was removed.
    """
    terms = _split_terms(terms_input)
    if not terms:
        print("ERROR: no keyword text provided.")
        return False

    custom = _load()
    removed, builtin, missing = [], [], []
    for term in terms:
        term_l = term.lower()
        match = None
        for tier in custom:
            match = next((k for k in custom[tier] if k.lower() == term_l), None)
            if match:
                custom[tier].remove(match)
                removed.append(match)
                break
        if match:
            continue
        # Not a custom keyword — categorize why we won't touch it.
        if _find_existing_tier(term) is not None:
            builtin.append(term)
        else:
            missing.append(term)

    if removed:
        _save(custom)
        print(f"Removed {len(removed)} custom keyword(s): "
              + ", ".join(f"'{t}'" for t in removed))
    if builtin:
        print("Refused (built-in — edit lpsc_monitor/config.py to change): "
              + ", ".join(f"'{t}'" for t in builtin))
    if missing:
        print("Not in your custom keywords: " + ", ".join(f"'{t}'" for t in missing))
    return bool(removed)
