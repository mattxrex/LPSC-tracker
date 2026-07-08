"""
Heartbeat / failure notification for the LPSC Bulletin Monitor.

This is the safeguard that makes a silent failure announce itself. It:
  1. records the time of every successful check (a small stamp file), and
  2. emails the admin if a check crashes, or if too long has passed since the
     last successful check.

The whole point is that the tool once stopped for months without anyone
noticing. With this in place, a crash or a stalled run turns into an email
instead of silence.
"""

import traceback
from datetime import datetime
from pathlib import Path

# Small file that records when a check last completed successfully.
STAMP_FILE = Path(__file__).parent / "data" / "last_success.txt"

# Warn the admin if no successful check has happened in this many days.
STALE_AFTER_DAYS = 4


def record_success():
    """Record 'right now' as the time of the last successful check."""
    STAMP_FILE.parent.mkdir(parents=True, exist_ok=True)
    STAMP_FILE.write_text(datetime.now().isoformat())


def _last_success():
    """Return the datetime of the last successful check, or None."""
    try:
        return datetime.fromisoformat(STAMP_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def warn_if_stale():
    """Email the admin if it has been too long since the last success."""
    last = _last_success()
    if last is None:
        return  # No baseline yet (first run) — nothing to compare against.

    days = (datetime.now() - last).days
    if days >= STALE_AFTER_DAYS:
        _safe_admin_alert(
            f"[LPSC Monitor] No successful check in {days} days",
            f"The last successful bulletin check was {last:%Y-%m-%d %H:%M}.\n"
            f"That is {days} days ago, which is longer than expected.\n\n"
            f"Checks may be failing or not running. Please investigate.",
        )


def notify_error(context, exc):
    """Email the admin with the traceback when a check crashes."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    _safe_admin_alert(
        f"[LPSC Monitor] Check failed: {context}",
        f"A scheduled check raised an error and did not complete:\n\n{tb}",
    )


def _safe_admin_alert(subject, message):
    """Send an admin alert, never letting the notifier itself crash the run."""
    try:
        from email_sender import send_admin_alert
        send_admin_alert(subject, message)
    except Exception as e:  # noqa: BLE001 — last-resort guard
        print(f"WARNING: could not send admin alert: {e}")
