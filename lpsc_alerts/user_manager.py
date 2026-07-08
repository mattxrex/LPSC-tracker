"""
User Manager for LPSC Alerts

Handles adding, removing, updating, and listing users.
Provides the logic behind the CLI user management commands.
"""

import re
from typing import List, Optional
import database as db


def _validate_email(email: str) -> bool:
    """Check that email has a basic valid format (something@something.something)."""
    return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email))


def change_email(old_email: str, new_email: str) -> bool:
    """
    Change a user's email address, preserving all their data.

    Dockets, keywords, and sent-alert history are linked to the user's internal
    id (not the email string), so they are unaffected by the change.
    """
    old_email = (old_email or "").strip()
    new_email = (new_email or "").strip()

    if not _validate_email(new_email):
        print(f"ERROR: '{new_email}' is not a valid email address.")
        return False
    if old_email.lower() == new_email.lower():
        print("ERROR: new email is the same as the current one — no change.")
        return False

    user = db.get_user_by_email(old_email)
    if not user:
        print(f"User not found: {old_email}")
        return False
    if db.get_user_by_email(new_email):
        print(f"ERROR: {new_email} is already a user. Choose a different address.")
        return False

    if db.update_user_email(user['id'], new_email):
        print(f"Changed email: {old_email} -> {new_email}")
        print("Tracked dockets, keywords, and alert history are unchanged.")
        return True

    print(f"ERROR: could not change email (is {new_email} already taken?).")
    return False


def _validate_docket(docket: str) -> bool:
    """Check that a docket number matches known LPSC formats.

    Accepted formats:
        U-12345, R-12345, I-12345, S-12345, X-12345, T-12345
        SPECIAL-123-2024
        GENERAL-123-2024
    """
    return bool(re.match(
        r'^[URISXT]-\d+$|^(SPECIAL|GENERAL)-\d+-\d{4}$',
        docket, re.IGNORECASE
    ))


def add_user(email: str, keywords: str = "", exclude: str = "",
             dockets: str = "") -> bool:
    """
    Add a new user with optional keywords and tracked dockets.

    Args:
        email: User's email address
        keywords: Comma-separated include keywords (e.g., "solar,Entergy")
        exclude: Comma-separated exclude keywords (e.g., "gas,water")
        dockets: Comma-separated docket numbers (e.g., "U-36625,U-37800")

    Returns:
        True if user was added, False if email already exists
    """
    if not _validate_email(email):
        print(f"Invalid email format: {email}")
        return False

    user_id = db.add_user(email, keywords.strip(), exclude.strip())

    if user_id is None:
        print(f"User {email} already exists.")
        return False

    # Add tracked dockets if provided
    if dockets:
        for docket in dockets.split(","):
            docket = docket.strip().upper()
            if docket:
                if not _validate_docket(docket):
                    print(f"  Skipping invalid docket format: {docket}")
                    continue
                db.add_tracked_docket(user_id, docket)

    print(f"Added user: {email}")
    if keywords:
        print(f"  Keywords: {keywords}")
    if exclude:
        print(f"  Exclude: {exclude}")
    if dockets:
        print(f"  Tracking: {dockets}")

    return True


def remove_user(email: str) -> bool:
    """Remove a user and all their data."""
    if db.remove_user(email):
        print(f"Removed user: {email}")
        return True
    else:
        print(f"User not found: {email}")
        return False


def list_users():
    """Print all users and their settings."""
    users = db.get_all_users()

    if not users:
        print("No users configured.")
        print("Add one with: python main.py add-user EMAIL --keywords 'solar,Entergy'")
        return

    print(f"\n{'='*60}")
    print(f"LPSC Alerts — {len(users)} user(s)")
    print(f"{'='*60}")

    for user in users:
        status = "active" if user['active'] else "INACTIVE"
        print(f"\n  {user['email']} [{status}]")

        if user['include_keywords']:
            print(f"    Include: {user['include_keywords']}")
        if user['exclude_keywords']:
            print(f"    Exclude: {user['exclude_keywords']}")

        dockets = db.get_tracked_dockets(user['id'])
        if dockets:
            print(f"    Tracking: {', '.join(dockets)}")

    print()


def update_user(email: str, add_keywords: str = None,
                remove_keywords: str = None, add_exclude: str = None,
                remove_exclude: str = None, add_dockets: str = None,
                remove_dockets: str = None) -> bool:
    """
    Update a user's keywords and/or tracked dockets.

    Keywords and dockets can be added or removed individually.

    Returns:
        True if user was found and updated, False if not found
    """
    user = db.get_user_by_email(email)
    if not user:
        print(f"User not found: {email}")
        return False

    # --- Update include keywords ---
    if add_keywords or remove_keywords:
        current = set(
            k.strip() for k in (user['include_keywords'] or '').split(',')
            if k.strip()
        )
        if add_keywords:
            for k in add_keywords.split(','):
                k = k.strip()
                if k:
                    current.add(k)
                    print(f"  Added keyword: {k}")
        if remove_keywords:
            for k in remove_keywords.split(','):
                k = k.strip()
                if k in current:
                    current.discard(k)
                    print(f"  Removed keyword: {k}")
                else:
                    print(f"  Keyword not found: {k}")
        db.update_user_keywords(email, include_keywords=','.join(sorted(current)))

    # --- Update exclude keywords ---
    if add_exclude or remove_exclude:
        current = set(
            k.strip() for k in (user['exclude_keywords'] or '').split(',')
            if k.strip()
        )
        if add_exclude:
            for k in add_exclude.split(','):
                k = k.strip()
                if k:
                    current.add(k)
                    print(f"  Added exclusion: {k}")
        if remove_exclude:
            for k in remove_exclude.split(','):
                k = k.strip()
                if k in current:
                    current.discard(k)
                    print(f"  Removed exclusion: {k}")
                else:
                    print(f"  Exclusion not found: {k}")
        db.update_user_keywords(email, exclude_keywords=','.join(sorted(current)))

    # --- Update tracked dockets ---
    if add_dockets:
        for d in add_dockets.split(','):
            d = d.strip().upper()
            if d:
                if not _validate_docket(d):
                    print(f"  Skipping invalid docket format: {d}")
                    continue
                if db.add_tracked_docket(user['id'], d):
                    print(f"  Now tracking: {d}")
                else:
                    print(f"  Already tracking: {d}")

    if remove_dockets:
        for d in remove_dockets.split(','):
            d = d.strip().upper()
            if d:
                if db.remove_tracked_docket(user['id'], d):
                    print(f"  Stopped tracking: {d}")
                else:
                    print(f"  Not tracking: {d}")

    print(f"Updated user: {email}")
    return True
