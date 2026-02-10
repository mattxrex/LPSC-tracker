"""
Bulletin Downloader for LPSC Portal

Copied from lpsc_monitor with import paths adjusted for lpsc_alerts.

Downloads bulletin PDFs from the LPSC website.
"""

import requests
import re
from pathlib import Path
from typing import Optional

from config import BULLETINS_DIR, LPSC_BASE_URL, log


def download_file(url: str, save_path: Path, timeout: int = 60) -> bool:
    """
    Download a file from a URL and save it locally.

    Returns True if download succeeded, False otherwise.
    """
    log(f"Downloading: {url}")
    log(f"Saving to: {save_path}")

    try:
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'application/pdf,*/*',
        }
        response = session.get(url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()

        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        file_size = save_path.stat().st_size
        log(f"Downloaded {file_size:,} bytes")

        with open(save_path, 'rb') as f:
            header = f.read(10)
            if not header.startswith(b'%PDF'):
                log("WARNING: Downloaded file may not be a valid PDF")
                return False

        return True

    except requests.exceptions.RequestException as e:
        log(f"ERROR downloading file: {e}")
        return False
    except IOError as e:
        log(f"ERROR saving file: {e}")
        return False


def download_bulletin_by_url(url: str, bulletin_number: int) -> Optional[Path]:
    """
    Download a bulletin PDF given its URL.

    Returns path to saved PDF if successful, None otherwise.
    """
    filename = f"bulletin_{bulletin_number}.pdf"
    save_path = BULLETINS_DIR / filename

    if save_path.exists():
        log(f"Bulletin {bulletin_number} already downloaded: {save_path}")
        return save_path

    if download_file(url, save_path):
        return save_path
    else:
        if save_path.exists():
            save_path.unlink()
        return None
