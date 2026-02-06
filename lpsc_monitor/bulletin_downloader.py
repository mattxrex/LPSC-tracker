"""
Bulletin Downloader for LPSC Portal

This module handles downloading bulletin PDFs from the LPSC website.

LPSC bulletins are available at:
https://lpscpubvalence.lpsc.louisiana.gov/

Bulletin PDFs have URLs like:
https://lpscpubvalence.lpsc.louisiana.gov/portal/PSC/ViewFile?fileId=2y0TzoU5Ob4%3D
"""

import requests
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs
import re

from config import BULLETINS_DIR, LPSC_BASE_URL, log


def download_file(url: str, save_path: Path, timeout: int = 60) -> bool:
    """
    Download a file from a URL and save it locally.

    Args:
        url: The URL to download from
        save_path: Where to save the downloaded file
        timeout: Request timeout in seconds

    Returns:
        True if download succeeded, False otherwise
    """
    log(f"Downloading: {url}")
    log(f"Saving to: {save_path}")

    try:
        # Use a session for better connection handling
        session = requests.Session()

        # Set headers to look like a browser (some sites block scripts)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'application/pdf,*/*',
        }

        response = session.get(url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()  # Raise exception for bad status codes

        # Check if we got a PDF (or at least some content)
        content_type = response.headers.get('Content-Type', '')
        log(f"Content-Type: {content_type}")

        # Save the file
        save_path.parent.mkdir(parents=True, exist_ok=True)

        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        file_size = save_path.stat().st_size
        log(f"Downloaded {file_size:,} bytes")

        # Basic validation - PDFs start with %PDF
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

    Args:
        url: Direct URL to the bulletin PDF
        bulletin_number: Bulletin number (for naming the saved file)

    Returns:
        Path to saved PDF if successful, None otherwise
    """
    # Create filename based on bulletin number
    filename = f"bulletin_{bulletin_number}.pdf"
    save_path = BULLETINS_DIR / filename

    # Check if already downloaded
    if save_path.exists():
        log(f"Bulletin {bulletin_number} already downloaded: {save_path}")
        return save_path

    # Download the file
    if download_file(url, save_path):
        return save_path
    else:
        # Clean up partial download if it exists
        if save_path.exists():
            save_path.unlink()
        return None


def download_bulletin_by_number(bulletin_number: int) -> Optional[Path]:
    """
    Attempt to download a bulletin by its number.

    NOTE: This requires knowing the URL pattern for bulletins.
    The LPSC portal uses encoded fileIds, so we can't easily construct
    URLs from bulletin numbers alone. This function is a placeholder
    for when we implement portal scraping.

    For now, use download_bulletin_by_url() with the direct URL.
    """
    log(f"WARNING: Cannot auto-download bulletin #{bulletin_number}")
    log("The LPSC portal uses encoded file IDs.")
    log("Please provide the direct PDF URL using download_bulletin_by_url()")
    return None


def get_bulletin_path(bulletin_number: int) -> Optional[Path]:
    """
    Get the local path to a bulletin PDF if it exists.

    Args:
        bulletin_number: The bulletin number to look for

    Returns:
        Path to the PDF if it exists locally, None otherwise
    """
    filename = f"bulletin_{bulletin_number}.pdf"
    path = BULLETINS_DIR / filename

    if path.exists():
        return path
    return None


def list_downloaded_bulletins() -> list:
    """
    List all bulletin PDFs that have been downloaded.

    Returns:
        List of (bulletin_number, path) tuples
    """
    bulletins = []

    for pdf_file in BULLETINS_DIR.glob("bulletin_*.pdf"):
        # Extract bulletin number from filename
        match = re.search(r'bulletin_(\d+)\.pdf', pdf_file.name)
        if match:
            number = int(match.group(1))
            bulletins.append((number, pdf_file))

    # Sort by bulletin number
    bulletins.sort(key=lambda x: x[0], reverse=True)
    return bulletins


# =============================================================================
# TESTING / CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    print("LPSC Bulletin Downloader")
    print("=" * 60)

    if len(sys.argv) < 3:
        print("\nUsage: python bulletin_downloader.py <url> <bulletin_number>")
        print("\nExample:")
        print("  python bulletin_downloader.py 'https://lpscpubvalence.lpsc.louisiana.gov/portal/PSC/ViewFile?fileId=xxx' 1352")

        print("\n\nCurrently downloaded bulletins:")
        bulletins = list_downloaded_bulletins()
        if bulletins:
            for num, path in bulletins:
                print(f"  Bulletin #{num}: {path}")
        else:
            print("  (none)")

        sys.exit(0)

    url = sys.argv[1]
    bulletin_number = int(sys.argv[2])

    print(f"\nDownloading bulletin #{bulletin_number}...")
    result = download_bulletin_by_url(url, bulletin_number)

    if result:
        print(f"\nSuccess! Saved to: {result}")
    else:
        print("\nFailed to download bulletin.")
        sys.exit(1)
