"""
dsk_generator.py — DSK Broker Notification PDF generator for Estrella PZ system.

Generates the DSK (Deklaracja Skrócona / broker notification) form for DHL shipments
by filling two fields in the pre-filled template PDF:
  - AWB           — DHL air waybill number, formatted as "XX XXXX XXXX"
  - Data i miejsce — generation date in DD-MM-YYYY Warszawa format

All other 17 fields are fixed in the template and are not touched.

Trigger conditions (carrier must be DHL AND either value > 2500 OR broker_required=True):
  - carrier.upper() == "DHL"
  - value_usd > 2500  OR  broker_required is True
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Default template path ────────────────────────────────────────────────────
_MODULE_DIR = Path(__file__).parent
_DEFAULT_TEMPLATE = _MODULE_DIR / "dsk_template.pdf"


def _format_awb(raw: str) -> tuple[str, str]:
    """
    Return (awb_clean, awb_formatted).

    awb_clean     — digits only, e.g. "2824221912"
    awb_formatted — grouped XX XXXX XXXX for 10-digit AWBs, else original with spaces preserved
    """
    awb_clean = re.sub(r"\s+", "", raw)

    # If already has spaces and not 10 bare digits after stripping, preserve as-is
    if len(awb_clean) == 10 and awb_clean.isdigit():
        awb_formatted = f"{awb_clean[0:2]} {awb_clean[2:6]} {awb_clean[6:10]}"
    else:
        # Non-standard length — keep spaces from original input
        awb_formatted = raw.strip()

    return awb_clean, awb_formatted


def _today_str() -> str:
    return datetime.now().strftime("%d-%m-%Y")


def _sha256_file(path: str) -> str:
    """Return SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_audit_log(output_dir: str, entry: dict) -> None:
    """
    Append an entry to dsk_audit_log.json in output_dir.
    Reads existing log, appends new entry, writes back.
    """
    log_path = Path(output_dir) / "dsk_audit_log.json"
    existing: list = []
    if log_path.is_file():
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    existing.append(entry)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


def _get_current_version(output_dir: str, awb_clean: str, date_str: str) -> int:
    """
    Return the highest version number already in the audit log for this AWB+date.
    Returns 0 if no prior entry exists.
    """
    log_path = Path(output_dir) / "dsk_audit_log.json"
    if not log_path.is_file():
        return 0
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        versions = [
            e.get("version", 1)
            for e in entries
            if isinstance(e, dict)
            and e.get("awb") == awb_clean
            and e.get("date") == date_str
        ]
        return max(versions) if versions else 0
    except Exception:
        return 0


def _fill_pdf_pypdf(template_path: str, output_path: str, fields: dict) -> bool:
    """
    Fill PDF using pypdf. Returns True on success, False if output looks corrupt.
    """
    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(template_path)
        writer = PdfWriter()
        writer.append(reader)
        writer.update_page_form_field_values(writer.pages[0], fields)

        with open(output_path, "wb") as f:
            writer.write(f)

        # Sanity check: output must be at least 10 KB (template is 199 KB)
        size = os.path.getsize(output_path)
        return size > 10_000

    except Exception:
        return False


def _fill_pdf_pymupdf(template_path: str, output_path: str, fields: dict) -> bool:
    """
    Fill PDF using PyMuPDF (fitz) as fallback. Returns True on success.
    """
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(template_path)
        page = doc[0]

        for widget in page.widgets():
            if widget.field_name in fields:
                widget.field_value = fields[widget.field_name]
                widget.update()

        doc.save(output_path, garbage=4, deflate=True)
        doc.close()

        size = os.path.getsize(output_path)
        return size > 10_000

    except Exception:
        return False


def generate_dsk(
    awb: str,
    value_usd: float,
    carrier: str = "DHL",
    broker_required: bool = True,
    output_dir: str = ".",
    template_path: str = None,
    date_override: str = None,
    # Legacy alias kept for backward compatibility
    require_broker: bool = None,
) -> dict:
    """
    Generate DSK broker notification PDF for DHL shipments.

    Parameters
    ----------
    awb              : raw AWB number, e.g. "2824221912" or "28 2422 1912"
    value_usd        : shipment value in USD (sum of all invoice CIF values)
    carrier          : carrier name (default "DHL")
    broker_required  : force-override — if True, generates regardless of value threshold
    output_dir       : directory where the output PDF is saved
    template_path    : path to DSK template PDF; defaults to dsk_template.pdf next to this module
    date_override    : DD-MM-YYYY string; defaults to today
    require_broker   : deprecated alias for broker_required (backward compat)

    Returns
    -------
    dict with keys:
        generated          : bool
        skip_reason        : None | "carrier_not_dhl" | "value_below_threshold_no_broker_flag"
                             | "broker_not_required"
        output_path        : str | None
        awb_clean          : str | None
        awb_formatted      : str | None
        date               : str | None
        filename           : str | None
        file_hash_sha256   : str | None
        version            : int | None
        regenerated        : bool | None
    """
    # ── Backward-compat: require_broker alias ────────────────────────────────
    if require_broker is not None and broker_required is True:
        # require_broker was explicitly passed; use it
        broker_required = require_broker

    # ── Input validation ──────────────────────────────────────────────────────
    errors = []
    if not awb or not str(awb).strip():
        errors.append("AWB is required")
    elif not re.match(r'^\d[\d\s]{7,14}\d$', str(awb).strip()):
        errors.append(f"AWB format invalid: '{awb}' — expected numeric DHL format")
    if not isinstance(value_usd, (int, float)) or value_usd < 0:
        errors.append("value_usd must be a non-negative number")
    if errors:
        raise ValueError("; ".join(errors))

    # ── Trigger conditions ────────────────────────────────────────────────────
    if carrier.upper() != "DHL":
        return {
            "generated":          False,
            "skip_reason":        "carrier_not_dhl",
            "output_path":        None,
            "awb_clean":          None,
            "awb_formatted":      None,
            "date":               None,
            "filename":           None,
            "file_hash_sha256":   None,
            "version":            None,
            "regenerated":        None,
        }

    should_generate = (
        carrier.upper() == "DHL"
        and (value_usd > 2500 or broker_required is True)
    )

    if not should_generate:
        return {
            "generated":          False,
            "skip_reason":        "value_below_threshold_no_broker_flag",
            "output_path":        None,
            "awb_clean":          None,
            "awb_formatted":      None,
            "date":               None,
            "filename":           None,
            "file_hash_sha256":   None,
            "version":            None,
            "regenerated":        None,
        }

    # ── Prepare values ────────────────────────────────────────────────────────
    awb_clean, awb_formatted = _format_awb(str(awb))
    date_str = date_override if date_override else _today_str()
    date_with_city = f"{date_str} Warszawa"

    filename = f"DSK_{awb_clean}_{date_str}.pdf"
    output_path = str(Path(output_dir) / filename)

    # ── Resolve template ──────────────────────────────────────────────────────
    tpl = str(template_path) if template_path else str(_DEFAULT_TEMPLATE)
    if not os.path.isfile(tpl):
        raise FileNotFoundError(f"DSK template not found: {tpl}")

    # ── Ensure output directory exists ────────────────────────────────────────
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # ── Version control: rename existing file if present ─────────────────────
    regenerated = False
    prior_version = _get_current_version(str(output_dir), awb_clean, date_str)
    new_version = prior_version + 1

    if Path(output_path).is_file():
        # Rename existing file to versioned backup
        versioned_name = f"DSK_{awb_clean}_{date_str}_v{prior_version}.pdf"
        versioned_path = str(Path(output_dir) / versioned_name)
        try:
            os.rename(output_path, versioned_path)
        except OSError:
            pass
        regenerated = True

    # ── Fields to fill ────────────────────────────────────────────────────────
    fields = {
        "AWB":            awb_formatted,
        "Data i miejsce": date_with_city,
    }

    # ── Try pypdf first, fall back to PyMuPDF ────────────────────────────────
    success = _fill_pdf_pypdf(tpl, output_path, fields)

    if not success:
        # Remove any corrupt partial output before retrying
        try:
            os.remove(output_path)
        except OSError:
            pass
        success = _fill_pdf_pymupdf(tpl, output_path, fields)

    if not success:
        raise RuntimeError(
            f"DSK PDF generation failed — neither pypdf nor PyMuPDF produced valid output. "
            f"Template: {tpl}"
        )

    # ── SHA256 hash ───────────────────────────────────────────────────────────
    file_hash = _sha256_file(output_path)

    # ── Write audit log ───────────────────────────────────────────────────────
    audit_entry = {
        "awb":              awb_clean,
        "awb_formatted":    awb_formatted,
        "date":             date_str,
        "value_usd":        float(value_usd),
        "carrier":          carrier.upper(),
        "broker_required":  bool(broker_required),
        "generated_at":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "filename":         filename,
        "file_hash_sha256": file_hash,
        "version":          new_version,
    }
    if regenerated:
        audit_entry["regenerated"] = True
    _write_audit_log(str(output_dir), audit_entry)

    return {
        "generated":          True,
        "skip_reason":        None,
        "output_path":        output_path,
        "awb_clean":          awb_clean,
        "awb_formatted":      awb_formatted,
        "date":               date_with_city,
        "filename":           filename,
        "file_hash_sha256":   file_hash,
        "version":            new_version,
        "regenerated":        regenerated,
    }


def build_dhl_email_package(
    batch_storage_dir: str,
    awb: str,
    dsk_path: str = None,
) -> dict:
    """
    Scan batch_storage_dir for relevant files and return a structured
    email package dict — NOT sending the email, just preparing it.

    Returns
    -------
    {
        "to": "roman@acspedycja.pl",
        "cc": "info@estrellajewels.eu",
        "subject": "AWB 28 2422 1912 – Powiadomienie Brokera / Broker Notification",
        "body_pl": "W załączniku przesyłamy dokumenty do odprawy celnej...",
        "body_en": "Please find attached documents for customs clearance...",
        "attachments": [
            {"label": "Invoice", "path": "/path/to/invoice.pdf"},
            {"label": "AWB", "path": "/path/to/awb.pdf"},
            {"label": "DSK Broker Notification", "path": "/path/to/DSK_xxx.pdf"},
        ],
        "missing": []   # list of attachment types not found
    }
    """
    _, awb_formatted = _format_awb(str(awb))
    storage = Path(batch_storage_dir)
    attachments = []
    missing = []

    # ── Scan for Invoice PDF ──────────────────────────────────────────────────
    invoice_files = (
        list(storage.glob("*Invoice*.pdf"))
        + list(storage.glob("*invoice*.pdf"))
        + list(storage.glob("*INVOICE*.pdf"))
    )
    if invoice_files:
        # Take first match; multi-invoice batches can be extended later
        attachments.append({"label": "Invoice", "path": str(invoice_files[0])})
    else:
        missing.append("Invoice")

    # ── Scan for AWB PDF ─────────────────────────────────────────────────────
    awb_files = (
        list(storage.glob("*AWB*.pdf"))
        + list(storage.glob("*awb*.pdf"))
        + list(storage.glob("*label*.pdf"))
        + list(storage.glob("*Label*.pdf"))
    )
    if awb_files:
        attachments.append({"label": "AWB", "path": str(awb_files[0])})
    else:
        missing.append("AWB")

    # ── DSK PDF — passed directly ─────────────────────────────────────────────
    if dsk_path and Path(dsk_path).is_file():
        attachments.append({"label": "DSK Broker Notification", "path": str(dsk_path)})
    else:
        missing.append("DSK Broker Notification")

    # ── Build email package ───────────────────────────────────────────────────
    subject = f"AWB {awb_formatted} – Powiadomienie Brokera / Broker Notification"

    body_pl = (
        f"Dzień dobry,\n\n"
        f"W załączniku przesyłamy dokumenty do odprawy celnej przesyłki DHL AWB {awb_formatted}:\n"
        f"  - Faktura handlowa (Invoice)\n"
        f"  - List przewozowy AWB\n"
        f"  - Powiadomienie brokera (DSK)\n\n"
        f"Prosimy o potwierdzenie przyjęcia dokumentów.\n\n"
        f"Pozdrawiamy,\n"
        f"Estrella Jewels"
    )

    body_en = (
        f"Dear Sir/Madam,\n\n"
        f"Please find attached documents for customs clearance of DHL shipment AWB {awb_formatted}:\n"
        f"  - Commercial Invoice\n"
        f"  - AWB (Air Waybill)\n"
        f"  - DSK Broker Notification\n\n"
        f"Please confirm receipt of the documents.\n\n"
        f"Best regards,\n"
        f"Estrella Jewels"
    )

    return {
        "to":          "roman@acspedycja.pl",
        "cc":          "info@estrellajewels.eu",
        "subject":     subject,
        "body_pl":     body_pl,
        "body_en":     body_en,
        "attachments": attachments,
        "missing":     missing,
    }


# ── Quick self-test when run directly ────────────────────────────────────────
if __name__ == "__main__":
    import json
    import tempfile

    print("=== DSK Generator Self-Test ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Test 1: successful generation — DHL, high value, broker_required=True
        result = generate_dsk(
            awb="2824221912",
            value_usd=9652.00,
            carrier="DHL",
            broker_required=True,
            output_dir=tmpdir,
            date_override="26-04-2026",
        )
        print("Test 1 — DHL, $9652, broker_required=True:")
        print(json.dumps(result, indent=2))
        if result["generated"]:
            size = os.path.getsize(result["output_path"])
            print(f"  Output size: {size:,} bytes")
        print()

        # Test 2: regeneration — same AWB, same date
        result1b = generate_dsk(
            awb="2824221912",
            value_usd=9652.00,
            carrier="DHL",
            broker_required=True,
            output_dir=tmpdir,
            date_override="26-04-2026",
        )
        print("Test 1b — regeneration (same AWB+date):")
        print(json.dumps(result1b, indent=2))
        print()

        # Test 3: carrier skip
        result2 = generate_dsk(awb="2824221912", value_usd=9652.00, carrier="FedEx")
        print("Test 2 — FedEx carrier:")
        print(json.dumps(result2, indent=2))
        print()

        # Test 4: value below threshold, no broker flag
        result3 = generate_dsk(awb="2824221912", value_usd=2100.00, carrier="DHL", broker_required=False)
        print("Test 3 — $2100, below threshold, broker_required=False:")
        print(json.dumps(result3, indent=2))
        print()

        # Test 5: value below threshold BUT broker_required=True (force override)
        result4 = generate_dsk(
            awb="2824221912",
            value_usd=800.00,
            carrier="DHL",
            broker_required=True,
            output_dir=tmpdir,
            date_override="26-04-2026",
        )
        print("Test 4 — $800, broker_required=True (force override):")
        print(json.dumps(result4, indent=2))
        print()

        # Test 6: AWB with spaces as input
        result5 = generate_dsk(
            awb="28 2422 1912",
            value_usd=5000.00,
            carrier="DHL",
            broker_required=True,
            output_dir=tmpdir,
            date_override="26-04-2026",
        )
        print("Test 5 — AWB with spaces as input:")
        print(json.dumps(result5, indent=2))
        print()

        # Test 7: audit log
        import json as _json
        log_path = Path(tmpdir) / "dsk_audit_log.json"
        if log_path.is_file():
            with open(log_path) as f:
                log = _json.load(f)
            print(f"Test 6 — Audit log ({len(log)} entries):")
            for e in log:
                print(f"  AWB={e['awb']} date={e['date']} v{e['version']} hash={e['file_hash_sha256'][:12]}...")
        print()

        # Test 8: email package builder
        pkg = build_dhl_email_package(tmpdir, "2824221912", result["output_path"])
        print("Test 7 — Email package:")
        print(json.dumps({k: v for k, v in pkg.items() if k not in ("body_pl", "body_en")}, indent=2))
        print()

    print("=== All tests complete ===")
