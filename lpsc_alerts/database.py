"""
Database layer for LPSC Alerts

SQLite database with tables for:
- users: email, keywords, active status
- tracked_dockets: specific docket numbers a user wants to watch
- sent_alerts: prevents duplicate alert emails
- bulletins: which bulletins have been processed
"""

import sqlite3
from typing import List, Dict, Optional
from config import DATABASE_PATH, log


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory enabled."""
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database():
    """Create all tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            include_keywords TEXT,
            exclude_keywords TEXT,
            active BOOLEAN DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tracked_dockets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            docket_number TEXT NOT NULL,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, docket_number)
        );

        CREATE TABLE IF NOT EXISTS sent_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            docket_number TEXT NOT NULL,
            bulletin_number INTEGER,
            document_id TEXT,
            alert_type TEXT,
            sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS bulletins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number INTEGER UNIQUE NOT NULL,
            date TEXT,
            pdf_path TEXT,
            processed_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    conn.close()
    log("Database initialized")


# =========================================================================
# USER OPERATIONS
# =========================================================================

def add_user(email: str, include_keywords: str = "",
             exclude_keywords: str = "") -> Optional[int]:
    """Add a new user. Returns user ID or None if email already exists."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO users (email, include_keywords, exclude_keywords) VALUES (?, ?, ?)",
            (email, include_keywords, exclude_keywords)
        )
        conn.commit()
        user_id = cursor.lastrowid
        log(f"Added user {email} (id={user_id})")
        return user_id
    except sqlite3.IntegrityError:
        log(f"User {email} already exists")
        return None
    finally:
        conn.close()


def remove_user(email: str) -> bool:
    """Remove a user and all their tracked dockets and sent alerts."""
    conn = get_connection()
    cursor = conn.execute("DELETE FROM users WHERE email = ?", (email,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    if deleted:
        log(f"Removed user {email}")
    return deleted


def get_user_by_email(email: str) -> Optional[Dict]:
    """Get a user by email address."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_user_email(user_id: int, new_email: str) -> bool:
    """
    Change a user's email address, keeping their id (and therefore all their
    tracked dockets, keywords, and sent-alert history) intact.

    Returns True on success, False if the new email is already taken.
    """
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE users SET email = ? WHERE id = ?", (new_email, user_id)
        )
        conn.commit()
        updated = cursor.rowcount > 0
        if updated:
            log(f"Changed email for user id={user_id} to {new_email}")
        return updated
    except sqlite3.IntegrityError:
        log(f"Cannot change email: {new_email} already exists")
        return False
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[Dict]:
    """Get a user by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_active_users() -> List[Dict]:
    """Get all active users."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM users WHERE active = 1 ORDER BY email"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_users() -> List[Dict]:
    """Get all users (active and inactive)."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM users ORDER BY email").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_user_keywords(email: str, include_keywords: str = None,
                         exclude_keywords: str = None) -> bool:
    """Update a user's keywords. Pass None to leave unchanged."""
    conn = get_connection()
    user = get_user_by_email(email)
    if not user:
        conn.close()
        return False

    if include_keywords is not None:
        conn.execute("UPDATE users SET include_keywords = ? WHERE email = ?",
                     (include_keywords, email))
    if exclude_keywords is not None:
        conn.execute("UPDATE users SET exclude_keywords = ? WHERE email = ?",
                     (exclude_keywords, email))
    conn.commit()
    conn.close()
    return True


# =========================================================================
# TRACKED DOCKET OPERATIONS
# =========================================================================

def add_tracked_docket(user_id: int, docket_number: str) -> bool:
    """Add a docket to a user's tracked list. Returns False if already tracked."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO tracked_dockets (user_id, docket_number) VALUES (?, ?)",
            (user_id, docket_number.upper())
        )
        conn.commit()
        log(f"User {user_id} now tracking {docket_number}")
        return True
    except sqlite3.IntegrityError:
        log(f"User {user_id} already tracking {docket_number}")
        return False
    finally:
        conn.close()


def remove_tracked_docket(user_id: int, docket_number: str) -> bool:
    """Remove a docket from a user's tracked list."""
    conn = get_connection()
    cursor = conn.execute(
        "DELETE FROM tracked_dockets WHERE user_id = ? AND docket_number = ?",
        (user_id, docket_number.upper())
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def get_tracked_dockets(user_id: int) -> List[str]:
    """Get all docket numbers tracked by a user."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT docket_number FROM tracked_dockets WHERE user_id = ? ORDER BY docket_number",
        (user_id,)
    ).fetchall()
    conn.close()
    return [r['docket_number'] for r in rows]


def get_all_tracked_dockets() -> List[Dict]:
    """Get all tracked dockets across all active users, with user info."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT td.docket_number, td.user_id, u.email
        FROM tracked_dockets td
        JOIN users u ON u.id = td.user_id
        WHERE u.active = 1
        ORDER BY td.docket_number
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# =========================================================================
# SENT ALERTS OPERATIONS
# =========================================================================

def was_alert_sent(user_id: int, docket_number: str,
                   bulletin_number: int = None,
                   document_id: str = None) -> bool:
    """Check if an alert was already sent to avoid duplicates."""
    conn = get_connection()

    if document_id:
        # Check by document ID (for docket tracking alerts)
        row = conn.execute(
            "SELECT id FROM sent_alerts WHERE user_id = ? AND document_id = ?",
            (user_id, document_id)
        ).fetchone()
    elif bulletin_number:
        # Check by bulletin + docket (for keyword match alerts)
        row = conn.execute(
            """SELECT id FROM sent_alerts
               WHERE user_id = ? AND docket_number = ? AND bulletin_number = ?""",
            (user_id, docket_number, bulletin_number)
        ).fetchone()
    else:
        row = None

    conn.close()
    return row is not None


def record_sent_alert(user_id: int, docket_number: str, alert_type: str,
                      bulletin_number: int = None, document_id: str = None):
    """Record that an alert was sent (prevents future duplicates)."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO sent_alerts
           (user_id, docket_number, bulletin_number, document_id, alert_type)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, docket_number, bulletin_number, document_id, alert_type)
    )
    conn.commit()
    conn.close()


# =========================================================================
# BULLETIN OPERATIONS
# =========================================================================

def get_bulletin(number: int) -> Optional[Dict]:
    """Get a bulletin by number."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM bulletins WHERE number = ?", (number,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def add_bulletin(number: int, date: str = None, pdf_path: str = None) -> int:
    """Add a bulletin record. Returns its ID."""
    conn = get_connection()
    cursor = conn.execute(
        """INSERT OR IGNORE INTO bulletins (number, date, pdf_path, processed_date)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
        (number, date, pdf_path)
    )
    conn.commit()

    # Get the ID (whether just inserted or already existed)
    row = conn.execute(
        "SELECT id FROM bulletins WHERE number = ?", (number,)
    ).fetchone()
    conn.close()
    return row['id']


def get_all_bulletins() -> List[Dict]:
    """Get all bulletins, most recent first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM bulletins ORDER BY number DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
