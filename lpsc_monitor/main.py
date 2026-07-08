"""
LPSC Bulletin Monitor - Main Script

This is the main entry point for the LPSC bulletin monitoring tool.
It orchestrates the download, parsing, filtering, and reporting process.

Usage:
    python main.py process <url> <bulletin_number>  - Download and process a bulletin
    python main.py report [bulletin_number]         - Generate a report
    python main.py stats                            - Show database statistics
    python main.py test <pdf_path>                  - Test parsing a local PDF
    python main.py fetch-docs [bulletin_number]      - Download new docket documents
    python main.py summarize [bulletin_number]       - Summarize documents with Claude AI
"""

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Import our modules
from config import log, DEBUG, BULLETINS_DIR, MONITOR_INTERVAL
import database as db
from bulletin_downloader import download_bulletin_by_url, get_bulletin_path, list_downloaded_bulletins
from bulletin_parser import (
    parse_bulletin, extract_bulletin_date, extract_next_bulletin_date,
    extract_text_from_pdf, DocketEntry
)
from filter import calculate_relevance, FilterResult


def process_bulletin(url: str, bulletin_number: int, date: str = None) -> bool:
    """
    Download, parse, and store a bulletin.

    This is the main processing pipeline:
    1. Download the bulletin PDF
    2. Extract the bulletin date from the PDF (if not provided)
    3. Parse docket entries from the PDF
    4. Score each docket for relevance
    5. Store everything in the database

    Args:
        url: Direct URL to the bulletin PDF
        bulletin_number: The bulletin number (e.g., 1352)
        date: Publication date (optional — extracted from PDF if not provided)

    Returns:
        True if processing succeeded, False otherwise
    """
    print(f"\n{'='*60}")
    print(f"Processing Bulletin #{bulletin_number}")
    print(f"{'='*60}")

    # Step 1: Initialize database
    print("\n[1/5] Initializing database...")
    db.init_database()

    # Step 2: Download the bulletin
    print(f"\n[2/5] Downloading bulletin from LPSC portal...")
    pdf_path = download_bulletin_by_url(url, bulletin_number)

    if not pdf_path:
        print("ERROR: Failed to download bulletin PDF")
        return False

    print(f"      Downloaded: {pdf_path}")

    # Step 3: Extract bulletin date and next bulletin date from PDF
    print("\n[3/6] Extracting dates from PDF...")
    full_text = extract_text_from_pdf(str(pdf_path))

    if not date:
        date = extract_bulletin_date(full_text)
        if date:
            print(f"      Bulletin date: {date}")
        else:
            print("      WARNING: Could not extract date from PDF")
    else:
        print(f"      Using provided date: {date}")

    next_bulletin_date = extract_next_bulletin_date(full_text)
    if next_bulletin_date:
        print(f"      Next bulletin date: {next_bulletin_date}")

    # Step 4: Add bulletin to database
    print("\n[4/6] Recording bulletin in database...")
    bulletin_id = db.add_bulletin(
        number=bulletin_number,
        date=date,
        pdf_url=url,
        pdf_path=str(pdf_path)
    )

    # Store next bulletin date if found
    if next_bulletin_date:
        db.update_next_bulletin_date(bulletin_id, next_bulletin_date)

    # Step 5: Parse the bulletin
    print("\n[5/6] Parsing bulletin PDF...")
    try:
        entries = parse_bulletin(str(pdf_path))
        print(f"      Found {len(entries)} utility-related docket entries")
    except Exception as e:
        print(f"ERROR parsing bulletin: {e}")
        return False

    # Step 6: Score and store each docket
    print("\n[6/6] Scoring dockets and saving to database...")
    relevant_count = 0

    for entry in entries:
        # Calculate relevance score
        result = calculate_relevance(entry.title, entry.raw_text)

        # Store in database
        db.add_docket(
            bulletin_id=bulletin_id,
            docket_number=entry.docket_number,
            docket_type=entry.docket_type,
            title=entry.title,
            description=entry.raw_text,
            is_relevant=result.is_relevant,
            priority_score=result.priority_score,
            keywords_matched=result.all_matches,
            subpart=entry.subpart,
        )

        if result.is_relevant:
            relevant_count += 1

    # Mark bulletin as processed
    db.mark_bulletin_processed(bulletin_id)

    print(f"\n      Stored {len(entries)} dockets ({relevant_count} marked relevant)")
    print(f"\n{'='*60}")
    print("PROCESSING COMPLETE")
    print(f"{'='*60}")

    return True


def generate_report(bulletin_number: Optional[int] = None) -> str:
    """
    Generate a text report of relevant dockets.

    Args:
        bulletin_number: If specified, report only for this bulletin.
                        Otherwise, report all relevant dockets.

    Returns:
        Formatted report text
    """
    lines = []
    lines.append("=" * 70)
    lines.append("LPSC BULLETIN MONITOR - RELEVANT DOCKETS REPORT")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 70)

    # Get relevant dockets
    if bulletin_number:
        bulletin = db.get_bulletin(bulletin_number)
        if not bulletin:
            return f"Bulletin #{bulletin_number} not found in database"

        dockets = db.get_relevant_dockets(bulletin['id'])
        lines.append(f"\nBulletin #{bulletin_number}")
    else:
        dockets = db.get_relevant_dockets()
        lines.append("\nAll Bulletins")

    lines.append("-" * 70)

    if not dockets:
        lines.append("\nNo relevant dockets found.")
    else:
        lines.append(f"\nFound {len(dockets)} relevant docket(s):\n")

        current_bulletin = None
        for docket in dockets:
            # Group by bulletin
            if docket['bulletin_number'] != current_bulletin:
                current_bulletin = docket['bulletin_number']
                if bulletin_number is None:
                    lines.append(f"\n--- Bulletin #{current_bulletin} ---\n")

            # Format docket entry
            lines.append(f"DOCKET: {docket['docket_number']}")
            lines.append(f"  Score: {docket['priority_score']} points")

            if docket['keywords_matched']:
                lines.append(f"  Keywords: {docket['keywords_matched']}")

            # Wrap title text
            title = docket['title']
            if len(title) > 100:
                title = title[:100] + "..."
            lines.append(f"  Title: {title}")
            lines.append("")

    # Add statistics
    lines.append("=" * 70)
    lines.append("STATISTICS")
    lines.append("-" * 70)
    stats = db.get_statistics()
    lines.append(f"Total bulletins processed: {stats['total_bulletins']}")
    lines.append(f"Total dockets found: {stats['total_dockets']}")
    lines.append(f"Relevant dockets: {stats['relevant_dockets']}")
    if stats['dockets_by_type']:
        lines.append("\nDockets by type:")
        for dtype, count in sorted(stats['dockets_by_type'].items()):
            lines.append(f"  {dtype}: {count}")
    lines.append("=" * 70)

    return "\n".join(lines)


def show_statistics():
    """Display database statistics."""
    db.init_database()
    stats = db.get_statistics()

    print("\nLPSC Monitor Database Statistics")
    print("=" * 40)
    print(f"Total bulletins processed: {stats['total_bulletins']}")
    print(f"Total dockets found:       {stats['total_dockets']}")
    print(f"Relevant dockets:          {stats['relevant_dockets']}")

    if stats['dockets_by_type']:
        print("\nDockets by type:")
        for dtype, count in sorted(stats['dockets_by_type'].items()):
            print(f"  {dtype}-dockets: {count}")

    print("\nDownloaded bulletins:")
    bulletins = list_downloaded_bulletins()
    if bulletins:
        for num, path in bulletins:
            print(f"  #{num}: {path.name}")
    else:
        print("  (none)")


def test_parse(pdf_path: str):
    """Test parsing a local PDF without saving to database."""
    print(f"\nTest parsing: {pdf_path}")
    print("=" * 60)

    try:
        entries = parse_bulletin(pdf_path)
        print(f"\nFound {len(entries)} utility docket entries\n")

        relevant_count = 0
        for entry in entries:
            result = calculate_relevance(entry.title, entry.raw_text)

            status = "RELEVANT" if result.is_relevant else "        "
            subpart_label = f" [{entry.subpart}]" if entry.subpart else ""
            print(f"[{status}] {entry.docket_number}{subpart_label} (score: {result.priority_score})")
            print(f"          {entry.title[:70]}...")
            if result.all_matches:
                print(f"          Keywords: {', '.join(result.all_matches)}")
            print()

            if result.is_relevant:
                relevant_count += 1

        print(f"\nSummary: {relevant_count} of {len(entries)} dockets are relevant")

    except Exception as e:
        print(f"ERROR: {e}")
        raise


def print_usage():
    """Print usage instructions."""
    print("""
LPSC Bulletin Monitor
=====================

Usage:
    python main.py check
        Check the LPSC RSS feed for new bulletins and process any found.
        This is a one-shot command: it checks once and exits.

    python main.py monitor
        Continuously monitor for new bulletins (checks every 24 hours).
        Press Ctrl+C to stop.

    python main.py process <url> <bulletin_number>
        Download and process a bulletin PDF from the LPSC portal.
        Example: python main.py process 'https://lpscpubvalence.lpsc.louisiana.gov/portal/PSC/ViewFile?fileId=xxx' 1352

    python main.py report [bulletin_number]
        Generate a report of relevant dockets.
        If bulletin_number is provided, report only that bulletin.

    python main.py stats
        Show database statistics.

    python main.py test <pdf_path>
        Test parsing a local PDF file without saving to database.
        Example: python main.py test data/bulletins/bulletin_1352.pdf

    python main.py fetch-docs [bulletin_number]
        Download new docket documents for a bulletin's relevant dockets.
        Only fetches documents filed within the ~2 week bulletin window.
        If no bulletin number given, uses the latest bulletin.
        Example: python main.py fetch-docs 1368

    python main.py summarize [bulletin_number]
        Summarize downloaded docket documents using Claude AI (Haiku).
        Only processes documents that haven't been summarized yet.
        If no bulletin number given, uses the latest bulletin.
        Example: python main.py summarize 1368

    python main.py email-report [bulletin_number]
        Generate an HTML email report and send it.
        If no bulletin number given, uses the latest bulletin.
        Email settings must be configured in .env file.

    python main.py cleanup [bulletin_number]
        Delete downloaded PDFs after processing to save disk space.
        Database retains all summaries and portal links.

    python main.py setup-schedule
        Install a macOS launchd job to run checks automatically
        on the next bulletin publication date.

    python main.py help
        Show this help message.
""")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(0)

    command = sys.argv[1].lower()

    if command == "check":
        from rss_monitor import check_for_new_bulletins
        from pathlib import Path
        from datetime import datetime as _dt

        # Check for --no-email flag (useful during testing)
        no_email = '--no-email' in sys.argv

        # Append a timestamped entry to check_history.log so there's always a record
        _history_log = Path(__file__).parent / "data" / "check_history.log"
        _history_log.parent.mkdir(parents=True, exist_ok=True)
        with open(_history_log, "a") as _f:
            _f.write(f"\n=== Check started: {_dt.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")

        # Heartbeat: warn the admin if it's been too long since a good check
        import heartbeat
        heartbeat.warn_if_stale()

        print("\nChecking LPSC RSS feed for new bulletins...")
        summary = check_for_new_bulletins()

        # Print summary
        print(f"\n{'='*60}")
        print("CHECK COMPLETE")
        print(f"{'='*60}")
        print(f"Bulletins in RSS feed:  {summary['feed_count']}")
        print(f"New bulletins found:    {summary['new_count']}")
        print(f"Successfully processed: {len(summary['processed'])}")
        if summary['processed']:
            print(f"  Processed: {', '.join(f'#{n}' for n in summary['processed'])}")
        if summary['errors']:
            print(f"  Errors:    {', '.join(f'#{n}' for n in summary['errors'])}")

        # Run the full pipeline for each successfully processed bulletin
        if summary['processed']:
            from document_fetcher import fetch_documents_for_bulletin
            from document_summarizer import summarize_documents_for_bulletin
            from storage import cleanup_bulletin_pdfs
            from email_report import generate_html_report
            from email_sender import send_report_email

            for bulletin_number in summary['processed']:
                print(f"\n{'='*60}")
                print(f"RUNNING FULL PIPELINE FOR BULLETIN #{bulletin_number}")
                print(f"{'='*60}")

                # 1. Fetch docket documents
                print("\n--- Fetching docket documents ---")
                fetch_documents_for_bulletin(bulletin_number)

                # 2. Summarize documents
                print("\n--- Summarizing documents ---")
                summarize_documents_for_bulletin(bulletin_number)

                # 3. Clean up PDFs (free disk space)
                print("\n--- Cleaning up PDFs ---")
                cleanup_bulletin_pdfs(bulletin_number)

                # 4. Generate and send email report
                if not no_email:
                    print("\n--- Sending email report ---")
                    html = generate_html_report(bulletin_number)
                    if html:
                        bulletin = db.get_bulletin(bulletin_number)
                        bulletin_date = bulletin.get('date') if bulletin else None
                        send_report_email(html, bulletin_number, bulletin_date)
                else:
                    print("\n--- Skipping email (--no-email flag) ---")

            # Print next bulletin date and update launchd schedule
            last_num = summary['processed'][-1]
            last_bulletin = db.get_bulletin(last_num)
            if last_bulletin and last_bulletin.get('next_bulletin_date'):
                print(f"\nNext bulletin expected: {last_bulletin['next_bulletin_date']}")

        # Note: the launchd schedule is a fixed interval now (see schedule_next.py),
        # so there is nothing to re-arm here — the job keeps firing on its own.

        # Append completion status to check history log
        _status = "errors" if summary['errors'] else ("new bulletins: " + ", ".join(f"#{n}" for n in summary['processed']) if summary['processed'] else "no new bulletins")
        with open(_history_log, "a") as _f:
            _f.write(f"    Result: {_status}\n")

        # Heartbeat: the check completed, so record this as a successful run.
        heartbeat.record_success()

        sys.exit(1 if summary['errors'] else 0)

    elif command == "monitor":
        from rss_monitor import check_for_new_bulletins
        hours = MONITOR_INTERVAL / 3600
        print(f"\nStarting LPSC Bulletin Monitor (checking every {hours:.0f} hours)")
        print("Press Ctrl+C to stop.\n")

        try:
            while True:
                print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking for new bulletins...")
                check_for_new_bulletins()
                print(f"\nNext check in {hours:.0f} hours. Waiting...")
                time.sleep(MONITOR_INTERVAL)
        except KeyboardInterrupt:
            print("\n\nMonitor stopped by user.")
            sys.exit(0)

    elif command == "process":
        if len(sys.argv) < 4:
            print("ERROR: process requires URL and bulletin number")
            print("Usage: python main.py process <url> <bulletin_number>")
            sys.exit(1)

        url = sys.argv[2]
        bulletin_number = int(sys.argv[3])
        success = process_bulletin(url, bulletin_number)
        sys.exit(0 if success else 1)

    elif command == "report":
        db.init_database()
        bulletin_number = int(sys.argv[2]) if len(sys.argv) > 2 else None
        report = generate_report(bulletin_number)
        print(report)

    elif command == "stats":
        show_statistics()

    elif command == "fetch-docs":
        from document_fetcher import fetch_documents_for_bulletin
        bulletin_number = int(sys.argv[2]) if len(sys.argv) > 2 else None
        fetch_documents_for_bulletin(bulletin_number)

    elif command == "summarize":
        from document_summarizer import summarize_documents_for_bulletin
        bulletin_number = int(sys.argv[2]) if len(sys.argv) > 2 else None
        summarize_documents_for_bulletin(bulletin_number)

    elif command == "cleanup":
        from storage import cleanup_bulletin_pdfs
        bulletin_number = int(sys.argv[2]) if len(sys.argv) > 2 else None
        cleanup_bulletin_pdfs(bulletin_number)

    elif command == "email-report":
        from email_report import generate_html_report
        from email_sender import send_report_email
        bulletin_number = int(sys.argv[2]) if len(sys.argv) > 2 else None

        if not bulletin_number:
            db.init_database()
            all_bulletins = db.get_all_bulletins()
            if not all_bulletins:
                print("ERROR: No bulletins in database.")
                sys.exit(1)
            bulletin_number = all_bulletins[0]['number']

        print(f"\nGenerating email report for Bulletin #{bulletin_number}...")
        html = generate_html_report(bulletin_number)
        if not html:
            sys.exit(1)

        bulletin = db.get_bulletin(bulletin_number)
        bulletin_date = bulletin.get('date') if bulletin else None

        # Save a copy for preview
        preview_path = Path(f"data/report_{bulletin_number}.html")
        preview_path.write_text(html)
        print(f"Report preview saved to: {preview_path}")

        send_report_email(html, bulletin_number, bulletin_date)

    elif command == "test":
        if len(sys.argv) < 3:
            print("ERROR: test requires a PDF path")
            print("Usage: python main.py test <pdf_path>")
            sys.exit(1)
        test_parse(sys.argv[2])

    elif command == "setup-schedule":
        from schedule_next import setup_schedule
        setup_schedule()

    elif command == "help":
        print_usage()

    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as _e:
        # If a scheduled check crashes, email the admin instead of failing silently.
        if len(sys.argv) > 1 and sys.argv[1].lower() == "check":
            import heartbeat
            heartbeat.notify_error("monitor check", _e)
        raise
