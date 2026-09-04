"""
AERO-ASTRA — ATHENA RAG: Document Downloader
=============================================
Downloads the NASA-HDBK-1002 Fault Management Handbook PDF from the
official NASA Technical Standards archive and saves it to the local
data/ directory for ingestion by the RAG pipeline.

Usage:
    python -m backend.athena.rag.download
    # or directly:
    python backend/athena/rag/download.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import urllib.request

log = logging.getLogger("athena.rag.download")

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parent / "data"
PDF_PATH = DATA_DIR / "NASA-HDBK-1002.pdf"

# NASA Technical Reports Server (NTRS) — confirmed working
NASA_HDBK_URL = (
    "https://ntrs.nasa.gov/api/citations/20150000893/downloads/20150000893.pdf"
)

# Secondary mirror — FM Handbook Draft
NASA_NTRS_FALLBACK = (
    "https://ntrs.nasa.gov/api/citations/20110007957/downloads/20110007957.pdf"
)


def download_pdf(url: str, dest: Path) -> bool:
    """
    Download a PDF from *url* to *dest*.
    Returns True on success, False on network/HTTP error.
    """
    log.info("Fetching: %s", url)
    try:
        headers = {"User-Agent": "AERO-ASTRA-RAG/1.0 (NASA HDBK download)"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()

        if len(data) < 1024:
            log.warning("Response too small (%d bytes) — likely an error page.", len(data))
            return False

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        log.info("Saved %d bytes → %s", len(data), dest)
        return True

    except Exception as exc:
        log.warning("Download failed from %s: %s", url, exc)
        return False


def ensure_handbook() -> Path:
    """
    Ensure NASA-HDBK-1002.pdf is present in data/.
    Downloads from primary URL, falls back to NTRS mirror.
    Raises RuntimeError if both fail.
    """
    if PDF_PATH.exists() and PDF_PATH.stat().st_size > 10_000:
        log.info("Handbook already present at %s (%d bytes)", PDF_PATH, PDF_PATH.stat().st_size)
        return PDF_PATH

    log.info("NASA-HDBK-1002 not found locally — downloading…")

    for url in [NASA_HDBK_URL, NASA_NTRS_FALLBACK]:
        if download_pdf(url, PDF_PATH):
            return PDF_PATH

    # Both URLs failed — emit a clear, actionable error
    raise RuntimeError(
        "Could not download NASA-HDBK-1002 from either source.\n"
        "Options:\n"
        "  1. Download manually from: https://ntrs.nasa.gov/citations/20110007957\n"
        f"  2. Place the PDF at: {PDF_PATH}\n"
        "  3. Re-run this script after placing the file."
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    try:
        path = ensure_handbook()
        print(f"\n✓ NASA-HDBK-1002 ready at: {path}")
        print(f"  Size: {path.stat().st_size / 1024:.1f} KB")
        sys.exit(0)
    except RuntimeError as e:
        print(f"\n✗ {e}", file=sys.stderr)
        sys.exit(1)
