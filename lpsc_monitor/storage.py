"""
Storage Cleanup for LPSC Bulletin Monitor

Deletes downloaded PDF files after processing to keep disk usage minimal.
The database retains all extracted text, summaries, and portal links,
so no information is lost — only the raw PDF files are removed.

This is safe to run because:
- Bulletin text has already been parsed and stored in the dockets table
- Document summaries have already been stored in the documents table
- Portal links are preserved for future reference
"""

import os
from pathlib import Path
from typing import Dict

from config import BULLETINS_DIR, DOCUMENTS_DIR, log
import database as db


def cleanup_bulletin_pdfs(bulletin_number: int = None) -> Dict:
    """
    Delete downloaded PDF files for a bulletin and its docket documents.

    After cleanup:
    - pdf_path is set to NULL in the bulletins table
    - pdf_path is set to NULL in the documents table
    - The actual PDF files are deleted from disk
    - Empty docket directories are removed

    Args:
        bulletin_number: Specific bulletin to clean up, or None for latest

    Returns:
        Dict with counts: bulletin_pdfs_deleted, doc_pdfs_deleted
    """
    db.init_database()

    # Find the bulletin
    if bulletin_number:
        bulletin = db.get_bulletin(bulletin_number)
        if not bulletin:
            print(f"ERROR: Bulletin #{bulletin_number} not found in database.")
            return {'bulletin_pdfs_deleted': 0, 'doc_pdfs_deleted': 0}
    else:
        all_bulletins = db.get_all_bulletins()
        if not all_bulletins:
            print("ERROR: No bulletins in database.")
            return {'bulletin_pdfs_deleted': 0, 'doc_pdfs_deleted': 0}
        bulletin = all_bulletins[0]
        bulletin_number = bulletin['number']

    print(f"\nCleaning up PDFs for Bulletin #{bulletin_number}")
    print("-" * 40)

    result = {'bulletin_pdfs_deleted': 0, 'doc_pdfs_deleted': 0}

    # Step 1: Delete document PDFs for all dockets in this bulletin
    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT doc.id, doc.pdf_path
        FROM documents doc
        JOIN dockets d ON doc.docket_id = d.id
        WHERE d.bulletin_id = ? AND doc.pdf_path IS NOT NULL
    """, (bulletin['id'],))

    doc_rows = cursor.fetchall()
    for row in doc_rows:
        pdf_path = Path(row['pdf_path'])
        if pdf_path.exists():
            pdf_path.unlink()
            log(f"Deleted: {pdf_path}")
            result['doc_pdfs_deleted'] += 1

            # Remove empty parent directory
            parent = pdf_path.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
                log(f"Removed empty directory: {parent}")

        # Set pdf_path to NULL in database
        cursor.execute("UPDATE documents SET pdf_path = NULL WHERE id = ?", (row['id'],))

    # Step 2: Delete the bulletin PDF itself
    if bulletin.get('pdf_path'):
        pdf_path = Path(bulletin['pdf_path'])
        if pdf_path.exists():
            pdf_path.unlink()
            log(f"Deleted bulletin PDF: {pdf_path}")
            result['bulletin_pdfs_deleted'] = 1

    # Set bulletin pdf_path to NULL
    cursor.execute("UPDATE bulletins SET pdf_path = NULL WHERE id = ?", (bulletin['id'],))

    conn.commit()
    conn.close()

    print(f"Deleted: {result['bulletin_pdfs_deleted']} bulletin PDF(s), "
          f"{result['doc_pdfs_deleted']} document PDF(s)")

    return result
