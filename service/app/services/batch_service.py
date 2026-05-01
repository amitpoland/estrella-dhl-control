from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from typing import List, Tuple

from fastapi import UploadFile, HTTPException, status

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger(__name__)

ALLOWED_MIME = {"application/pdf"}
ALLOWED_EXT  = {".pdf"}


def _validate_file(file: UploadFile) -> None:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only PDF files are accepted. Got: {file.filename!r}",
        )
    if file.content_type and file.content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unexpected MIME type: {file.content_type}",
        )


def _safe_filename(filename: str) -> str:
    name = Path(filename).name                          # strip any path component
    name = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
    return name or "file.pdf"


async def save_batch(
    invoices: List[UploadFile],
    zc429:    UploadFile,
) -> Tuple[str, Path, Path]:
    """
    Validate, save uploads, return (batch_id, invoice_dir, zc429_path).
    """
    if not invoices:
        raise HTTPException(status_code=400, detail="At least one invoice PDF is required.")
    if not zc429:
        raise HTTPException(status_code=400, detail="ZC429 PDF is required.")

    for f in [*invoices, zc429]:
        _validate_file(f)

    batch_id   = uuid.uuid4().hex
    batch_root = settings.storage_root / "incoming" / batch_id
    batch_root.mkdir(parents=True, exist_ok=True)

    inv_dir = batch_root / "invoices"
    inv_dir.mkdir()

    for upload in invoices:
        dest = inv_dir / _safe_filename(upload.filename or "invoice.pdf")
        content = await upload.read()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail=f"File too large: {upload.filename}")
        dest.write_bytes(content)
        log.info("Saved invoice %s → %s", upload.filename, dest)

    zc_content = await zc429.read()
    if len(zc_content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"File too large: {zc429.filename}")
    zc429_path = batch_root / _safe_filename(zc429.filename or "zc429.pdf")
    zc429_path.write_bytes(zc_content)
    log.info("Saved ZC429 %s → %s", zc429.filename, zc429_path)

    return batch_id, inv_dir, zc429_path


def get_output_dir(batch_id: str) -> Path:
    d = settings.storage_root / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def cleanup_working(batch_id: str) -> None:
    d = settings.storage_root / "working" / batch_id
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        log.debug("Cleaned working dir for batch %s", batch_id)
