"""
Launchd Schedule for LPSC Alerts

Installs a macOS launchd plist that runs `python main.py check` periodically.

Why an interval instead of a fixed clock time: a laptop is often asleep or off
at any given minute, and launchd does NOT replay a fixed-time run that was
missed while the machine was off. Running on an interval (plus once at load and
automatically on wake from sleep) means the check runs whenever the Mac is
actually on, without depending on it being awake at one specific moment.

How macOS launchd works:
- A .plist file in ~/Library/LaunchAgents/ tells macOS when to run a script
- StartInterval runs the job every N seconds the machine is powered on, and
  launchd runs a missed interval as soon as the Mac wakes from sleep
- RunAtLoad also runs it once right after login/boot (and on install)
- After installing the plist, we load it so macOS picks up the schedule
"""

import os
import plistlib
import subprocess
from pathlib import Path


PLIST_NAME = "com.lpsc-alerts.check.plist"
PLIST_INSTALL_PATH = Path.home() / "Library" / "LaunchAgents" / PLIST_NAME

# How often to run the check while the Mac is powered on (seconds).
# The check is cheap (fetch RSS, poll tracked dockets, skip anything already
# seen), so running a few times a day costs almost nothing and greatly raises
# the odds of catching a bulletin the same day it posts.
CHECK_INTERVAL_SECONDS = 6 * 60 * 60  # every 6 hours


def create_plist():
    """
    Create the launchd plist dictionary.

    Generates a plist that runs `python main.py check` every few hours
    using this tool's own venv Python.
    """
    venv_python = Path(__file__).parent / "venv" / "bin" / "python"
    main_script = Path(__file__).parent / "main.py"
    working_dir = str(Path(__file__).parent)
    log_path = str(Path(__file__).parent / "data" / "launchd.log")

    plist = {
        'Label': 'com.lpsc-alerts.check',
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

    Called by `python main.py setup-schedule`.
    """
    print("\nSetting up LPSC Alerts scheduled checks")
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
    print(f"Log output: {plist['StandardOutPath']}")
    print(f"\nTo uninstall: launchctl unload ~/Library/LaunchAgents/{PLIST_NAME}")


def _reload_launchd():
    """Unload and reload the launchd plist to apply changes."""
    # Unload first (ignore errors if not currently loaded)
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


def _get_uid() -> int:
    """Get the current user's UID for launchctl commands."""
    return os.getuid()
