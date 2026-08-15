"""Chrome headless HTML → PDF adapter (ONE print path for branded documents).

Used by Commercial Packing List export so Preview/Download/Hub/email share
the same presentation definition rendered to PDF. Does not invent layout —
callers supply complete HTML.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)


def find_chrome_executable() -> Optional[str]:
    env = (os.environ.get("CHROME_PATH") or os.environ.get("PZ_CHROME_PATH") or "").strip()
    if env and Path(env).is_file():
        return env
    for cand in _CHROME_CANDIDATES:
        if Path(cand).is_file():
            return cand
    which = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("msedge")
    return which


def html_to_pdf_bytes(html: str, *, timeout_sec: int = 90) -> bytes:
    """Render ``html`` to PDF bytes via Chrome/Edge ``--print-to-pdf``.

    Raises RuntimeError when Chrome is missing or the print fails.
    """
    chrome = find_chrome_executable()
    if not chrome:
        raise RuntimeError(
            "Chrome/Edge not found for HTML→PDF export. "
            "Install Google Chrome or set CHROME_PATH."
        )

    with tempfile.TemporaryDirectory(prefix="ej-html-pdf-") as tmp:
        tmp_path = Path(tmp)
        html_path = tmp_path / "document.html"
        pdf_path = tmp_path / "document.pdf"
        html_path.write_text(html, encoding="utf-8")
        # file:// URL — Chrome requires absolute path form on Windows.
        file_url = html_path.resolve().as_uri()
        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--deny-permission-prompts",
            f"--print-to-pdf={pdf_path}",
            "--no-pdf-header-footer",
            file_url,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Chrome PDF print timed out after {timeout_sec}s") from exc
        if proc.returncode != 0 or not pdf_path.is_file():
            err = (proc.stderr or b"").decode("utf-8", errors="replace")[:800]
            raise RuntimeError(
                f"Chrome PDF print failed (rc={proc.returncode}): {err or 'no stderr'}"
            )
        data = pdf_path.read_bytes()
        if len(data) < 100 or not data.startswith(b"%PDF"):
            raise RuntimeError("Chrome PDF print produced invalid PDF bytes")
        return data
