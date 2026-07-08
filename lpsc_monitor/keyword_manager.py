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


def _builtin_only(tier):
    """Built-in keywords for a tier (the merged list minus the user's custom ones)."""
    custom_lower = {k.lower() for k in config.CUSTOM_KEYWORDS[tier]}
    return [k for k in config.KEYWORD_TIERS[tier][0] if k.lower() not in custom_lower]


def _find_existing_tier(term):
    """Return the tier a term is already in (built-in or custom), or None."""
    term_l = term.lower()
    for tier, (kw_list, _pts) in config.KEYWORD_TIERS.items():
        if any(k.lower() == term_l for k in kw_list):
            return tier
    return None


def print_keywords():
    """Print all keyword tiers with their weights; mark user-added ones."""
    print("\nLPSC Monitor — Keywords")
    print("=" * 60)
    for tier in ("high", "medium", "exclude"):
        pts = _points(tier)
        builtin = _builtin_only(tier)
        custom = config.CUSTOM_KEYWORDS[tier]
        print(f"\n{TIER_LABELS[tier]} ({pts:+d} points each) — "
              f"{len(builtin) + len(custom)} terms")
        for k in builtin:
            print(f"    {k}")
        for k in custom:
            print(f"    {k}  (custom)")
    print(f"\nRelevance threshold: {config.RELEVANCE_THRESHOLD}+ points = relevant.")
    if not any(config.CUSTOM_KEYWORDS.values()):
        print("\nNo custom keywords yet. Add one with:")
        print('    python main.py add-keyword "your term" high')
    print()


def add_keyword(term, tier_input):
    """Add a custom keyword to a tier. Returns True on success."""
    term = (term or "").strip()
    if not term:
        print("ERROR: keyword text is empty.")
        return False

    tier = TIER_ALIASES.get((tier_input or "").strip().lower())
    if tier is None:
        print(f"ERROR: unknown weight '{tier_input}'. Use: high, medium, or exclude.")
        return False

    existing = _find_existing_tier(term)
    if existing is not None:
        where = "custom" if term.lower() in {k.lower() for k in config.CUSTOM_KEYWORDS[existing]} else "built-in"
        print(f"'{term}' is already a {where} keyword in the {TIER_LABELS[existing]} tier — no change.")
        return False

    custom = _load()
    custom[tier].append(term)
    _save(custom)
    print(f"Added '{term}' to {TIER_LABELS[tier]} ({_points(tier):+d} points).")
    print("It will be used on the next check.")
    return True


def remove_keyword(term):
    """Remove a custom keyword. Built-in keywords can't be removed here. Returns bool."""
    term = (term or "").strip()
    term_l = term.lower()
    custom = _load()

    for tier in custom:
        match = next((k for k in custom[tier] if k.lower() == term_l), None)
        if match:
            custom[tier].remove(match)
            _save(custom)
            print(f"Removed custom keyword '{match}' from {TIER_LABELS[tier]}.")
            return True

    # Not a custom keyword — explain why we won't touch it.
    if _find_existing_tier(term) is not None:
        print(f"'{term}' is a built-in keyword and can't be removed with this command.")
        print("Edit lpsc_monitor/config.py to change the built-in lists.")
    else:
        print(f"'{term}' is not in your custom keywords.")
    return False
