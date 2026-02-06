"""
Database operations for LPSC Bulletin Monitor

This module handles all interactions with the SQLite database.
SQLite is a simple file-based database that's perfect for this project -
no server needed, just a single .db file.

Tables:
- bulletins: Tracks downloaded bulletin PDFs
- dockets: Individual docket entries extracted from bulletins
- documents: Documents downloaded for specific dockets (Phase 2)
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from config import DATABASE_PATH, log


def get_connection():
    """
    Create a connection to the SQLite database.

    The database file is created automatically if it doesn't exist.
    We use row_factory to get dict-like results instead of tuples.
    """
    conn = sqlite3.connect(DATABASE_PATH)
    # This lets us access columns by name (e.g., row['docket_number'])
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """
    Create all database tables if they don't exist.

    Run this once when setting up the project, or it will safely
    do nothing if tables already exist (CREATE TABLE IF NOT EXISTS).
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Table 1: Bulletins
    # Stores metadata about each downloaded bulletin PDF
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bulletins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number INTEGER UNIQUE NOT NULL,
            date TEXT,
            pdf_url TEXT,
            pdf_path TEXT,
            processed_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Table 2: Dockets
    # Individual docket entries extracted from bulletins
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dockets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bulletin_id INTEGER NOT NULL,
            docket_number TEXT NOT NULL,
            docket_type TEXT,
            title TEXT,
            description TEXT,
            is_relevant BOOLEAN DEFAULT 0,
            priority_score INTEGER DEFAULT 0,
            keywords_matched TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (bulletin_id) REFERENCES bulletins(id),
            UNIQUE(bulletin_id, docket_number)
        )
    """)

    # Table 3: Documents (for Phase 2)
    # Downloaded documents related to specific dockets
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            docket_id INTEGER NOT NULL,
            document_url TEXT,
            document_type TEXT,
            pdf_path TEXT,
            summary TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (docket_id) REFERENCES dockets(id)
        )
    """)

    # Create indexes for faster queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dockets_relevant
        ON dockets(is_relevant)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dockets_bulletin
        ON dockets(bulletin_id)
    """)

    # --- Migrations for new columns ---
    # Add subpart column to dockets (if not already present)
    _add_column_if_missing(cursor, 'dockets', 'subpart', 'TEXT')
    # Add next_bulletin_date column to bulletins (if not already present)
    _add_column_if_missing(cursor, 'bulletins', 'next_bulletin_date', 'TEXT')

    conn.commit()
    conn.close()
    log("Database initialized successfully")


def _add_column_if_missing(cursor, table: str, column: str, col_type: str):
    """
    Add a column to a table if it doesn't already exist.

    SQLite doesn't have IF NOT EXISTS for ALTER TABLE, so we check
    the table's column list first using PRAGMA table_info.
    """
    cursor.execute(f"PRAGMA table_info({table})")
    existing_columns = [row[1] for row in cursor.fetchall()]
    if column not in existing_columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        log(f"Added column '{column}' to '{table}' table")


# =============================================================================
# BULLETIN OPERATIONS
# =============================================================================

def add_bulletin(number: int, date: str = None, pdf_url: str = None,
                 pdf_path: str = None) -> int:
    """
    Add a new bulletin to the database.

    Args:
        number: Bulletin number (e.g., 1352)
        date: Publication date (optional)
        pdf_url: URL where bulletin was downloaded from
        pdf_path: Local path to saved PDF

    Returns:
        The ID of the newly created bulletin record
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO bulletins (number, date, pdf_url, pdf_path)
        VALUES (?, ?, ?, ?)
    """, (number, date, pdf_url, pdf_path))

    conn.commit()
    bulletin_id = cursor.lastrowid

    # If INSERT OR IGNORE skipped (bulletin exists), get existing ID
    if bulletin_id == 0:
        cursor.execute("SELECT id FROM bulletins WHERE number = ?", (number,))
        bulletin_id = cursor.fetchone()['id']

    conn.close()
    log(f"Added/found bulletin #{number} with ID {bulletin_id}")
    return bulletin_id


def get_bulletin(number: int) -> Optional[Dict]:
    """Get a bulletin by its number."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bulletins WHERE number = ?", (number,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_bulletin_date(bulletin_id: int, date: str):
    """Update the date for an existing bulletin."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE bulletins SET date = ? WHERE id = ? AND date IS NULL
    """, (date, bulletin_id))
    conn.commit()
    conn.close()


def update_next_bulletin_date(bulletin_id: int, next_date: str):
    """Store the next bulletin's mailing date for a bulletin."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE bulletins SET next_bulletin_date = ? WHERE id = ?
    """, (next_date, bulletin_id))
    conn.commit()
    conn.close()
    log(f"Updated next_bulletin_date for bulletin ID {bulletin_id}: {next_date}")


def mark_bulletin_processed(bulletin_id: int):
    """Mark a bulletin as processed (parsing complete)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE bulletins
        SET processed_date = ?
        WHERE id = ?
    """, (datetime.now().isoformat(), bulletin_id))
    conn.commit()
    conn.close()


def get_all_bulletins() -> List[Dict]:
    """Get all bulletins, most recent first."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bulletins ORDER BY number DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# =============================================================================
# DOCKET OPERATIONS
# =============================================================================

def add_docket(bulletin_id: int, docket_number: str, docket_type: str,
               title: str, description: str = None, is_relevant: bool = False,
               priority_score: int = 0, keywords_matched: List[str] = None,
               subpart: str = None) -> int:
    """
    Add a new docket entry to the database.

    Args:
        bulletin_id: ID of the bulletin this docket came from
        docket_number: Full docket number (e.g., "U-37800")
        docket_type: Single letter type (e.g., "U")
        title: Docket title/description from bulletin
        description: Additional description text
        is_relevant: Whether this docket matches our filter criteria
        priority_score: Numeric relevance score
        keywords_matched: List of keywords that matched
        subpart: Bulletin subpart letter (A-J)

    Returns:
        The ID of the newly created docket record
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Convert keywords list to comma-separated string for storage
    keywords_str = ",".join(keywords_matched) if keywords_matched else None

    try:
        cursor.execute("""
            INSERT INTO dockets
            (bulletin_id, docket_number, docket_type, title, description,
             is_relevant, priority_score, keywords_matched, subpart)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (bulletin_id, docket_number, docket_type, title, description,
              is_relevant, priority_score, keywords_str, subpart))
        conn.commit()
        docket_id = cursor.lastrowid
        log(f"Added docket {docket_number} with ID {docket_id}")
    except sqlite3.IntegrityError:
        # Docket already exists for this bulletin
        cursor.execute("""
            SELECT id FROM dockets
            WHERE bulletin_id = ? AND docket_number = ?
        """, (bulletin_id, docket_number))
        docket_id = cursor.fetchone()['id']
        log(f"Docket {docket_number} already exists with ID {docket_id}")

    conn.close()
    return docket_id


def get_relevant_dockets(bulletin_id: int = None) -> List[Dict]:
    """
    Get all relevant dockets, optionally filtered by bulletin.

    Args:
        bulletin_id: If provided, only get dockets from this bulletin

    Returns:
        List of docket dictionaries
    """
    conn = get_connection()
    cursor = conn.cursor()

    if bulletin_id:
        cursor.execute("""
            SELECT d.*, b.number as bulletin_number
            FROM dockets d
            JOIN bulletins b ON d.bulletin_id = b.id
            WHERE d.is_relevant = 1 AND d.bulletin_id = ?
            ORDER BY d.priority_score DESC
        """, (bulletin_id,))
    else:
        cursor.execute("""
            SELECT d.*, b.number as bulletin_number
            FROM dockets d
            JOIN bulletins b ON d.bulletin_id = b.id
            WHERE d.is_relevant = 1
            ORDER BY b.number DESC, d.priority_score DESC
        """)

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_dockets_by_bulletin(bulletin_id: int) -> List[Dict]:
    """Get all dockets (relevant or not) from a specific bulletin."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM dockets
        WHERE bulletin_id = ?
        ORDER BY docket_type, docket_number
    """, (bulletin_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_docket_by_number(docket_number: str) -> Optional[Dict]:
    """Get the most recent entry for a docket number."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.*, b.number as bulletin_number
        FROM dockets d
        JOIN bulletins b ON d.bulletin_id = b.id
        WHERE d.docket_number = ?
        ORDER BY b.number DESC
        LIMIT 1
    """, (docket_number,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# =============================================================================
# DOCUMENT OPERATIONS
# =============================================================================

def add_document(docket_id: int, document_url: str, document_type: str = None,
                 pdf_path: str = None) -> int:
    """
    Add a downloaded document record to the database.

    Args:
        docket_id: ID of the docket this document belongs to
        document_url: URL the document was downloaded from (used for dedup)
        document_type: Type of document (e.g., "Order", "Filing")
        pdf_path: Local path to the saved PDF

    Returns:
        The ID of the newly created document record
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO documents (docket_id, document_url, document_type, pdf_path)
        VALUES (?, ?, ?, ?)
    """, (docket_id, document_url, document_type, pdf_path))

    conn.commit()
    doc_id = cursor.lastrowid
    conn.close()
    log(f"Added document ID {doc_id} for docket_id {docket_id}")
    return doc_id


def get_documents_by_docket(docket_id: int) -> List[Dict]:
    """Get all documents for a specific docket."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM documents
        WHERE docket_id = ?
        ORDER BY created_at DESC
    """, (docket_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_document_summary(document_id: int, summary: str):
    """
    Store an AI-generated summary for a document.

    Args:
        document_id: ID of the document record
        summary: The summary text to store
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE documents SET summary = ? WHERE id = ?
    """, (summary, document_id))
    conn.commit()
    conn.close()
    log(f"Updated summary for document ID {document_id}")


def get_unsummarized_documents(bulletin_id: int = None) -> List[Dict]:
    """
    Get documents that have a PDF on disk but no summary yet.

    Joins with the dockets table to include docket_number, title, and
    document_type — needed to build a good summarization prompt.

    Args:
        bulletin_id: If provided, only get docs for this bulletin's dockets

    Returns:
        List of document dicts with extra docket info
    """
    conn = get_connection()
    cursor = conn.cursor()

    if bulletin_id:
        cursor.execute("""
            SELECT doc.id, doc.pdf_path, doc.document_type,
                   d.docket_number, d.title as docket_title
            FROM documents doc
            JOIN dockets d ON doc.docket_id = d.id
            WHERE doc.summary IS NULL
              AND doc.pdf_path IS NOT NULL
              AND d.bulletin_id = ?
            ORDER BY d.docket_number, doc.id
        """, (bulletin_id,))
    else:
        cursor.execute("""
            SELECT doc.id, doc.pdf_path, doc.document_type,
                   d.docket_number, d.title as docket_title
            FROM documents doc
            JOIN dockets d ON doc.docket_id = d.id
            WHERE doc.summary IS NULL
              AND doc.pdf_path IS NOT NULL
            ORDER BY d.docket_number, doc.id
        """)

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_document_by_url(document_url: str) -> Optional[Dict]:
    """
    Check if a document with this URL has already been downloaded.
    Used for deduplication so we don't download the same document twice.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM documents WHERE document_url = ?", (document_url,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# =============================================================================
# STATISTICS / REPORTING
# =============================================================================

def get_statistics() -> Dict:
    """Get summary statistics about the database."""
    conn = get_connection()
    cursor = conn.cursor()

    stats = {}

    cursor.execute("SELECT COUNT(*) FROM bulletins")
    stats['total_bulletins'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM dockets")
    stats['total_dockets'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM dockets WHERE is_relevant = 1")
    stats['relevant_dockets'] = cursor.fetchone()[0]

    cursor.execute("""
        SELECT docket_type, COUNT(*) as count
        FROM dockets
        GROUP BY docket_type
    """)
    stats['dockets_by_type'] = {row['docket_type']: row['count']
                                for row in cursor.fetchall()}

    conn.close()
    return stats


# =============================================================================
# INITIALIZATION
# =============================================================================

if __name__ == "__main__":
    # When run directly, initialize the database
    print("Initializing LPSC Monitor database...")
    init_database()
    print(f"Database created at: {DATABASE_PATH}")
    print("\nCurrent statistics:")
    stats = get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")
