"""
Launchd Schedule for LPSC Alerts

Installs a macOS launchd plist that runs `python main.py check` daily at 6 AM.
Unlike lpsc_monitor (which dynamically updates its schedule based on the next
bulletin date), lpsc_alerts uses a fixed daily schedule because it monitors
both bulletins and tracked dockets.

How macOS launchd works:
- A .plist file in ~/Library/LaunchAgents/ tells macOS when to run a script
- The StartCalendarInterval key sets the day/time to run
- After installing the plist, we load it so macOS picks up the schedule
"""

import os
import plistlib
import subprocess
from pathlib import Path


PLIST_NAME = "com.lpsc-alerts.check.plist"
PLIST_INSTALL_PATH = Path.home() / "Library" / "LaunchAgents" / PLIST_NAME


def create_plist():
    """
    Create the launchd plist dictionary.

    Generates a plist that runs `python main.py check` daily at 6 AM
    using the shared venv Python (located in lpsc_monitor/venv/).
    """
    # Shared venv lives in lpsc_monitor/
    venv_python = Path(__file__).parent.parent / "lpsc_monitor" / "venv" / "bin" / "python"
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
        'StartCalendarInterval': {
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

    print(f"\nScheduled check is now active.")
    print(f"Schedule: Daily at 6:00 AM")
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
