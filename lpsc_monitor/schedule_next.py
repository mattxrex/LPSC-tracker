"""
Launchd Schedule for LPSC Bulletin Monitor

Installs a macOS launchd plist that runs `python main.py check` periodically.

This used to reschedule itself after every run, aiming the launchd job at the
next expected bulletin date. That was fragile: the job fired on a single
calendar date and had to successfully re-arm itself each time, so one run that
found nothing (or crashed) left the schedule stuck in the past with no future
trigger — which is exactly how the monitor silently stopped for months.

Now it runs on a simple interval instead (like lpsc_alerts). The check is cheap
and skips anything already processed, so running a few times a day whenever the
Mac is on is both robust and self-correcting — there is nothing to re-arm.

How macOS launchd works:
- A .plist file in ~/Library/LaunchAgents/ tells macOS when to run a script
- StartInterval runs the job every N seconds the machine is powered on, and
  launchd runs a missed interval as soon as the Mac wakes from sleep
- RunAtLoad also runs it once right after login/boot (and on install)
"""

import plistlib
import subprocess
from pathlib import Path

from config import log

# Where the plist lives once installed
PLIST_NAME = "com.lpsc-monitor.check.plist"
PLIST_INSTALL_PATH = Path.home() / "Library" / "LaunchAgents" / PLIST_NAME

# The plist template lives alongside this script
PLIST_TEMPLATE_PATH = Path(__file__).parent / PLIST_NAME

# How often to run the check while the Mac is powered on (seconds).
CHECK_INTERVAL_SECONDS = 6 * 60 * 60  # every 6 hours


def update_schedule():
    """
    Kept for backward compatibility with callers (e.g. `main.py check`).

    With the interval-based schedule there is nothing to re-arm after a run —
    launchd keeps firing on its own — so this is intentionally a no-op beyond a
    short log line. The scheduling itself is installed once by setup_schedule().
    """
    print("Periodic schedule active — no per-run rescheduling needed.")


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
    project's virtual environment Python on a fixed interval.
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
        'StartInterval': CHECK_INTERVAL_SECONDS,
        'RunAtLoad': True,
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

    hours = CHECK_INTERVAL_SECONDS // 3600
    print(f"\nScheduled check is now active.")
    print(f"Schedule: every {hours} hours while the Mac is on (plus on login/wake)")
    print(f"Log output will go to: {plist['StandardOutPath']}")

    print("\nTo uninstall: launchctl unload ~/Library/LaunchAgents/com.lpsc-monitor.check.plist")
