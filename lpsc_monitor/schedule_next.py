"""
Launchd Schedule Updater for LPSC Bulletin Monitor

After each successful bulletin check, this script reads the next bulletin
date from the database and updates the macOS launchd plist to run on that
date (at 6 AM).

How macOS launchd works:
- A .plist file in ~/Library/LaunchAgents/ tells macOS when to run a script
- The StartCalendarInterval key sets the day/time to run
- After updating the plist, we unload and reload it so macOS picks up the change

This script is called automatically at the end of a successful `check` run.
"""

import plistlib
import subprocess
from datetime import datetime
from pathlib import Path

from config import log
import database as db

# Where the plist lives once installed
PLIST_NAME = "com.lpsc-monitor.check.plist"
PLIST_INSTALL_PATH = Path.home() / "Library" / "LaunchAgents" / PLIST_NAME

# The plist template lives alongside this script
PLIST_TEMPLATE_PATH = Path(__file__).parent / PLIST_NAME


def update_schedule():
    """
    Read the next bulletin date from the database and update the launchd
    schedule to run on that date at 6 PM.

    If the plist is installed, it will be unloaded and reloaded with the
    new schedule. If not installed, prints a reminder to run setup-schedule.
    """
    db.init_database()

    # Get the latest bulletin's next_bulletin_date
    all_bulletins = db.get_all_bulletins()
    if not all_bulletins:
        log("No bulletins in database, can't update schedule")
        return

    latest = all_bulletins[0]
    next_date_str = latest.get('next_bulletin_date')

    if not next_date_str:
        print("No next bulletin date available — schedule not updated")
        return

    # Parse the date
    try:
        next_date = datetime.strptime(next_date_str, "%Y-%m-%d")
    except ValueError:
        print(f"ERROR: Could not parse next bulletin date: {next_date_str}")
        return

    print(f"Next bulletin date: {next_date_str}")
    print(f"Scheduling check for: {next_date.strftime('%A, %B %d, %Y')} at 6:00 AM")

    if not PLIST_INSTALL_PATH.exists():
        print(f"NOTE: Launchd plist not installed. Run 'python main.py setup-schedule' first.")
        return

    # Read the current plist
    with open(PLIST_INSTALL_PATH, 'rb') as f:
        plist = plistlib.load(f)

    # Update the StartCalendarInterval to the next bulletin date at 6 PM
    plist['StartCalendarInterval'] = {
        'Month': next_date.month,
        'Day': next_date.day,
        'Hour': 6,
        'Minute': 0,
    }

    # Write the updated plist
    with open(PLIST_INSTALL_PATH, 'wb') as f:
        plistlib.dump(plist, f)

    # Reload the launchd job so macOS picks up the new schedule
    _reload_launchd()

    print("Schedule updated successfully.")


def _reload_launchd():
    """Unload and reload the launchd plist to apply changes."""
    label = "com.lpsc-monitor.check"

    # Unload (ignore errors if not currently loaded)
    subprocess.run(
        ['launchctl', 'bootout', f'gui/{_get_uid()}', str(PLIST_INSTALL_PATH)],
        capture_output=True
    )

    # Load
    result = subprocess.run(
        ['launchctl', 'bootstrap', f'gui/{_get_uid()}', str(PLIST_INSTALL_PATH)],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        # Fall back to legacy load/unload commands
        subprocess.run(
            ['launchctl', 'unload', str(PLIST_INSTALL_PATH)],
            capture_output=True
        )
        subprocess.run(
            ['launchctl', 'load', str(PLIST_INSTALL_PATH)],
            capture_output=True
        )

    log("Launchd job reloaded")


def _get_uid() -> int:
    """Get the current user's UID for launchctl commands."""
    import os
    return os.getuid()


def create_plist():
    """
    Create the launchd plist file from scratch.

    This generates a plist that runs `python main.py check` using the
    project's virtual environment Python. It starts with a default
    schedule that gets updated after the first successful run.
    """
    # Use the venv's Python interpreter
    venv_python = Path(__file__).parent / "venv" / "bin" / "python"
    main_script = Path(__file__).parent / "main.py"
    working_dir = str(Path(__file__).parent)
    log_path = str(Path(__file__).parent / "data" / "launchd.log")

    plist = {
        'Label': 'com.lpsc-monitor.check',
        'ProgramArguments': [
            str(venv_python),
            str(main_script),
            'check',
        ],
        'WorkingDirectory': working_dir,
        'StartCalendarInterval': {
            # Default: run every other Friday at 6 PM
            # This gets updated after each successful check
            'Weekday': 5,  # Friday
            'Hour': 6,
            'Minute': 0,
        },
        'StandardOutPath': log_path,
        'StandardErrorPath': log_path,
        'EnvironmentVariables': {
            'PATH': '/usr/local/bin:/usr/bin:/bin',
        },
    }

    return plist


def setup_schedule():
    """
    Install the launchd plist and load it.

    This is called by `python main.py setup-schedule`.
    """
    print("\nSetting up LPSC Bulletin Monitor scheduled checks")
    print("=" * 50)

    # Create the plist
    plist = create_plist()

    # Ensure ~/Library/LaunchAgents/ exists
    PLIST_INSTALL_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Write the plist
    with open(PLIST_INSTALL_PATH, 'wb') as f:
        plistlib.dump(plist, f)

    print(f"Installed plist: {PLIST_INSTALL_PATH}")

    # Load it
    _reload_launchd()

    print(f"\nScheduled check is now active.")
    print(f"Log output will go to: {plist['StandardOutPath']}")

    # Try to set the initial schedule from the database
    all_bulletins = db.get_all_bulletins()
    if all_bulletins and all_bulletins[0].get('next_bulletin_date'):
        next_date = all_bulletins[0]['next_bulletin_date']
        print(f"\nNext check scheduled for: {next_date} at 6:00 AM")
        update_schedule()
    else:
        print("\nNo next bulletin date in database yet.")
        print("Default: will check every Friday at 6 AM.")
        print("The schedule will auto-update after the first successful check.")

    print("\nTo uninstall: launchctl unload ~/Library/LaunchAgents/com.lpsc-monitor.check.plist")
