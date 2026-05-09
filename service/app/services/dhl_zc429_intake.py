"""
dhl_zc429_intake.py — DHL Agencja Celna WAW "ZC429 received" email intake.

Purpose
-------
When DHL's automated WAW customs agency sends the
"Powiadomienie o odebranym komunikacie ZC429" notification, this
service:

  1. Classifies the inbound email as a ZC429 completion notice.
  2. Extracts AWB + ZC/MRN number from subject + body.
  3. Locates the matching shipment batch by AWB.
  4. Saves email evidence under storage/email_evidence/by_awb/<awb>/.
  5. Classifies and stores every attachment under the right shipment
     subfolder.
  6. Writes a `customs_declaration` block in audit.json marking SAD/
     ZC429 received (matches the existing audit schema) plus
     timeline event ``zc429_received``.

What this service NEVER does
----------------------------
- It does NOT call wFirma (no Proforma / customer / product writes).
- It does NOT create a PZ document.
- It does NOT mutate invoice values, freight, duty, CIF, VAT or any
  customs financial field. Only ``customs_declaration.mrn`` is set;
  everything else stays untouched.
- It does NOT send any SMTP reply.
- It does NOT change config flags or trigger automatic observers.
- It does NOT alter the existing low-value (< 2500 USD) DHL self-
  clearance workflow. That flow operates upstream (proactive dispatch
  → poland-arrival → SAD unlock → PZ); this intake just records the
  ZC429 outcome whenever DHL sends it, regardless of value tier.

Idempotency
-----------
Re-running for the same ``message_id`` is a no-op. Attachments are
deduplicated by content SHA via the email-evidence store; identical
content is never written twice. ``customs_declaration`` updates are
overwrites of well-known scalar fields, so re-runs are safe.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.config import settings
from ..core.logging import get_logger
from ..core import timeline as tl
from . import customs_doc_classifier as _cdc
from . import email_evidence_store as _evs
from . import intake_lineage as _lineage

log = get_logger(__name__)

INTAKE_SOURCE_KIND   = "dhl_zc429_email"
PROCESSING_VERSION   = _lineage.PROCESSING_VERSION


# ── Detector rules ───────────────────────────────────────────────────────────

DHL_WAW_SENDER       = "plwawecs@dhl.com"
SUBJECT_TOKEN        = "zc429"
SUBJECT_PL_PHRASE    = "powiadomienie o odebranym komunikacie"
BODY_PL_COMPLETED    = "odprawa celna"
BODY_PL_COMPLETED_2  = "zakończona"        # accent-tolerant compare elsewhere
BODY_EN_SUBSTITUTES  = "substitutes the paper sad"

# AWB: DHL Express AWBs are 10-digit numeric. Prefer the AWB explicitly
# named in the subject; the body sometimes templates the placeholder.
_AWB_RE  = re.compile(r"\b(\d{10})\b")

# ZC / MRN: 18-char alphanumeric like "26PL44302D00AUCWR3" — start with
# 2-digit year, country code, fixed-width tail. Lookarounds (instead of
# \b) so the underscore-separated DHL filename
#   "ZC429_26PL44302D00AUCWR3_1_PL.xml"
# still matches — \b would fail because "_" counts as a word char.
_MRN_RE  = re.compile(
    r"(?<![A-Za-z0-9])(\d{2}PL\d{5}[A-Z0-9]{9,10})(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def is_dhl_zc429_email(
    *,
    sender:  str = "",
    subject: str = "",
    body:    str = "",
) -> bool:
    """Return True if the sender + subject + body match the
    DHL WAW ZC429 completion notification pattern.

    All three signals are required:
      • sender contains ``plwawecs@dhl.com``
      • subject mentions ZC429 (or the Polish "Powiadomienie..." phrase)
      • body declares customs clearance completed
    """
    s_lo  = (sender  or "").lower()
    sub_lo= (subject or "").lower()
    bd_lo = (body    or "").lower()
    if DHL_WAW_SENDER not in s_lo:
        return False
    if (SUBJECT_TOKEN not in sub_lo) and (SUBJECT_PL_PHRASE not in sub_lo):
        return False
    # Body must show the "odprawa celna ... zakończona" or English
    # "substitutes the paper SAD" wording — guards against unrelated
    # plwawecs notifications that re-use the brand template.
    if (BODY_PL_COMPLETED in bd_lo and "zako" in bd_lo) or BODY_EN_SUBSTITUTES in bd_lo:
        return True
    return False


def extract_identifiers(
    *,
    subject: str,
    body:    str,
    attachments_filenames: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Pull AWB + ZC/MRN from the email. Subject wins over body; body
    wins over attachment filenames. All return values are str (never
    None) so callers can safely use them as dict keys.
    """
    awb = ""
    mrn = ""
    for src in (subject or "", body or ""):
        if not awb:
            m = _AWB_RE.search(src)
            if m: awb = m.group(1)
        if not mrn:
            m = _MRN_RE.search(src)
            if m: mrn = m.group(1).upper()
        if awb and mrn:
            break
    if (not awb or not mrn) and attachments_filenames:
        for fn in attachments_filenames:
            if not awb:
                m = _AWB_RE.search(fn)
                if m: awb = m.group(1)
            if not mrn:
                m = _MRN_RE.search(fn)
                if m: mrn = m.group(1).upper()
            if awb and mrn:
                break
    return {"awb": awb, "zc_number": mrn}


# ── Attachment classification ───────────────────────────────────────────────

# Map customs_doc_classifier output → shipment subfolder.
_SHIPMENT_SUBDIR = {
    "customs_xml":     "source/dhl_zc429",   # raw ZC429 XMLs
    "customs_pdf":     "source/dhl_zc429",   # ZC429 PDFs (scanned receipt)
    "customs_html":    "source/dhl_zc429",
    "invoice":         "source/invoices",
    "awb":             "source/awb",
    "email_evidence":  "source/email",
    "duty_note":       "source/dhl_zc429",
    "polish_desc":     "source/other",
    "payment":         "source/other",
    "other":           "source/other",
    "unknown":         "source/other",
}

# Convenience aggregator buckets used in the timeline payload + audit.
_BUCKET = {
    "customs_xml":    "zc429",
    "customs_pdf":    "zc429",
    "customs_html":   "zc429",
    "invoice":        "invoices",
    "awb":            "awb",
    "email_evidence": "mail_evidence",
    "duty_note":      "others",
    "polish_desc":    "others",
    "payment":        "others",
    "other":          "others",
    "unknown":        "others",
}


def classify_attachments(
    attachments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Run the customs-doc classifier on every attachment.

    Each input dict must have ``filename`` (str). Optional ``content``
    (bytes) and ``size`` are passed through. Returns a new list with
    ``type``, ``confidence``, ``bucket``, ``shipment_subdir`` added.
    Unknown/uncertain types are preserved as ``other`` (never dropped).
    """
    out: List[Dict[str, Any]] = []
    for a in attachments or []:
        fn  = (a.get("filename") or "").strip()
        cls = _cdc.classify(fn)
        t   = cls.get("type") or "unknown"
        out.append({
            **a,
            "filename":         fn,
            "type":             t,
            "confidence":       cls.get("confidence") or "low",
            "bucket":           _BUCKET.get(t, "others"),
            "shipment_subdir":  _SHIPMENT_SUBDIR.get(t, "source/other"),
        })
    return out


def aggregate_buckets(classified: List[Dict[str, Any]]) -> Dict[str, int]:
    """Counts per high-level bucket for audit + timeline payload."""
    buckets = {"zc429": 0, "invoices": 0, "awb": 0,
               "mail_evidence": 0, "others": 0}
    for a in classified or []:
        b = a.get("bucket") or "others"
        buckets[b] = buckets.get(b, 0) + 1
    return buckets


# ── Batch resolution ────────────────────────────────────────────────────────

def find_batch_id_by_awb(awb: str) -> Optional[str]:
    """Walk ``storage_root/outputs/*/audit.json`` looking for the audit
    whose ``tracking_no`` (or batch_id suffix) matches *awb*. Read-only.
    Returns the first match or None.
    """
    if not awb:
        return None
    root = Path(settings.storage_root) / "outputs"
    if not root.exists():
        return None
    awb = awb.strip()
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        ap = d / "audit.json"
        if not ap.exists():
            continue
        # Cheap pre-check on the directory name
        if awb in d.name:
            return d.name
        try:
            audit = json.loads(ap.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (str(audit.get("tracking_no") or "").strip() == awb
                or str(audit.get("awb") or "").strip() == awb):
            return d.name
    return None


# ── Disk persistence ────────────────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    """Trim DHL's exotic characters down to a filesystem-safe name.

    Preserves the original suffix and the first few semantic tokens so
    the operator can still tell files apart by glance. Collisions are
    handled by the caller via SHA-content suffix.
    """
    n = (name or "").strip()
    n = re.sub(r"[^\w.\-]+", "_", n).strip("._-")
    return n or "attachment.bin"


def _save_attachment_to_shipment(
    *,
    batch_id:       str,
    classified:     Dict[str, Any],
    content:        bytes,
) -> Path:
    """Write ``content`` into ``outputs/<batch_id>/<shipment_subdir>/``.

    Returns the resolved path. Idempotent: if a file with identical
    content already exists at the target, the existing path is reused
    (the SHA check guarantees byte-equality).
    """
    base = Path(settings.storage_root) / "outputs" / batch_id
    sub  = classified.get("shipment_subdir") or "source/other"
    dest_dir = base / sub
    dest_dir.mkdir(parents=True, exist_ok=True)
    fn = _safe_filename(classified.get("filename") or "attachment.bin")
    dest = dest_dir / fn
    if dest.exists():
        try:
            existing = dest.read_bytes()
            if hashlib.sha256(existing).hexdigest() == \
               hashlib.sha256(content).hexdigest():
                return dest
        except Exception:
            pass
        # Same name, different content → suffix with first 8 hex of SHA.
        sha8 = hashlib.sha256(content).hexdigest()[:8]
        stem, dot, ext = fn.rpartition(".")
        if dot:
            dest = dest_dir / f"{stem}.{sha8}.{ext}"
        else:
            dest = dest_dir / f"{fn}.{sha8}"
    dest.write_bytes(content)
    return dest


# ── Audit + timeline updates ────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_audit(
    audit_path:       Path,
    *,
    awb:              str,
    zc_number:        str,
    sender:           str,
    subject:          str,
    received_at:      str,
    attachment_count: int,
    classified:       List[Dict[str, Any]],
    evidence_path:    str,
    intake_event_id:  str = "",
) -> Dict[str, Any]:
    """Atomically update ``customs_declaration`` and append a
    ``zc429_intake`` provenance block. Never overwrites unrelated keys.

    Financial fields (CIF, duty, freight, totals, VAT) are NOT touched.
    """
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    cd = audit.get("customs_declaration") or {}
    # Preserve any prior MRN match — operator may have a manual SAD
    # already imported. Only set when missing or equal to the new MRN.
    prior_mrn = (cd.get("mrn") or "").strip().upper()
    if not prior_mrn:
        cd["mrn"] = zc_number
    elif prior_mrn != zc_number.upper():
        cd.setdefault("alternate_mrns", [])
        if zc_number not in cd["alternate_mrns"]:
            cd["alternate_mrns"].append(zc_number)

    cd["received"]            = True
    cd["source"]              = "dhl_zc429_email"
    cd["awb"]                 = awb
    cd["zc_number"]           = zc_number
    cd["email_sender"]        = sender
    cd["email_subject"]       = subject
    cd["received_at"]         = received_at or _now_iso()
    cd["attachments_count"]   = attachment_count
    cd["evidence_path"]       = evidence_path
    cd["intake_event_id"]     = intake_event_id
    cd["processing_version"]  = PROCESSING_VERSION
    cd["documents"]           = [
        {
            "filename":         c.get("filename"),
            "type":             c.get("type"),
            "bucket":           c.get("bucket"),
            "confidence":       c.get("confidence"),
            "stored_at":        c.get("stored_at", ""),
            "sha256":           c.get("sha256", ""),
            "size":             c.get("size", 0),
            "intake_event_id":  intake_event_id,
            "lineage_id":       c.get("lineage_id", ""),
        }
        for c in classified
    ]
    audit["customs_declaration"] = cd

    # Atomic write
    tmp = audit_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(audit, ensure_ascii=False, default=str),
                   encoding="utf-8")
    tmp.replace(audit_path)
    return cd


# ── Public entry point ─────────────────────────────────────────────────────

def ingest_zc429_email(
    *,
    sender:       str,
    subject:      str,
    body:         str,
    received_at:  str = "",
    message_id:   str = "",
    attachments:  Optional[List[Dict[str, Any]]] = None,
    batch_id:     Optional[str] = None,
) -> Dict[str, Any]:
    """Full intake pipeline. Returns a structured result. Never raises
    in normal failure modes; surfaces ``ok=False`` with a reason.

    Inputs
    ------
    attachments : list of {filename, content (bytes), size?}
                  ``content`` is required for any file we want to store
                  to disk; missing content rows are still classified
                  and returned but flagged ``stored_at=""``.

    Returns
    -------
    {
      ok:             bool,
      reason:         str (when not ok),
      awb:            str,
      zc_number:      str,
      batch_id:       str or "",
      attachment_count: int,
      classified:     [ … ],
      buckets:        { zc429, invoices, awb, mail_evidence, others },
      stored_files:   [paths],
      audit_updated:  bool,
      timeline_logged: bool,
      duplicate:      bool,    # True if message_id already processed
    }
    """
    out: Dict[str, Any] = {
        "ok":                 False,
        "reason":             "",
        "awb":                "",
        "zc_number":          "",
        "batch_id":           batch_id or "",
        "attachment_count":   0,
        "classified":         [],
        "buckets":            {},
        "stored_files":       [],
        "audit_updated":      False,
        "timeline_logged":    False,
        "duplicate":          False,
        "intake_event_id":    "",
        "processing_version": PROCESSING_VERSION,
    }
    attachments = attachments or []

    # 1. Detection gate
    if not is_dhl_zc429_email(sender=sender, subject=subject, body=body):
        out["reason"] = "not_a_zc429_email"
        return out

    # 2. AWB + MRN
    ids = extract_identifiers(
        subject=subject, body=body,
        attachments_filenames=[a.get("filename","") for a in attachments],
    )
    out["awb"]       = ids["awb"]
    out["zc_number"] = ids["zc_number"]
    if not ids["awb"]:
        out["reason"] = "awb_not_found"
        return out
    if not ids["zc_number"]:
        out["reason"] = "zc_number_not_found"
        return out

    # 3. Batch resolution (caller may pre-resolve)
    if not out["batch_id"]:
        out["batch_id"] = find_batch_id_by_awb(out["awb"]) or ""
    if not out["batch_id"]:
        out["reason"] = "batch_not_found_for_awb"
        return out

    # 4. Lineage event — get_or_create over (kind, message_id). Same
    #    DHL email always returns the same intake_event_id, so a
    #    reprocess is fully traceable to the original event.
    effective_msg_id = (message_id
                        or f"zc429-{out['awb']}-{out['zc_number']}")
    was_existing = False
    if _lineage._db_path is not None:
        try:
            event_row, was_existing = _lineage.get_or_create_intake_event(
                source_kind       = INTAKE_SOURCE_KIND,
                source_message_id = effective_msg_id,
                source_sender     = sender,
                source_subject    = subject,
                awb               = out["awb"],
                zc_number         = out["zc_number"],
                batch_id          = out["batch_id"],
                received_at       = received_at or _now_iso(),
            )
            out["intake_event_id"] = event_row["intake_event_id"]
        except Exception as exc:
            log.warning("[zc429-intake] lineage create failed (non-fatal): %s", exc)
            was_existing = False
    else:
        # Lineage DB not initialised — fall back to the email-evidence
        # store check so the legacy idempotency contract still holds.
        if message_id:
            try:
                doc = _evs.get_by_awb(out["awb"])
                for thr in doc.get("threads", []):
                    for m in thr.get("messages", []):
                        if (m.get("message_id") == message_id
                                and m.get("event_type") == "agency_zc429_received"):
                            was_existing = True
                            out["attachment_count"] = len(m.get("attachments") or [])
                            break
                    if was_existing:
                        break
            except Exception:
                pass

    # If lineage says we've seen this exact email before, short-circuit
    # safely. We still re-link the batch and append a processing note
    # so the history is honest about the reprocess attempt.
    if was_existing:
        out["ok"]        = True
        out["duplicate"] = True
        out["reason"]    = "already_ingested"
        prior_atts       = _lineage.list_attachments(out["intake_event_id"])
        out["attachment_count"] = len(prior_atts)
        out["buckets"]   = aggregate_buckets([
            {"bucket": a.get("bucket", "others")} for a in prior_atts
        ])
        try:
            _lineage.record_processing_note(
                intake_event_id=out["intake_event_id"],
                note=f"reprocess_skipped: duplicate ingest of message_id="
                     f"{effective_msg_id}",
                actor="dhl_zc429_intake",
            )
        except Exception:
            pass
        return out

    # 5. Classify + persist attachments
    classified = classify_attachments(attachments)
    out["attachment_count"] = len(classified)

    audit_path = (Path(settings.storage_root) / "outputs"
                  / out["batch_id"] / "audit.json")
    if not audit_path.exists():
        out["reason"] = f"audit_not_found_at_{audit_path}"
        return out

    stored_files: List[str] = []
    evs_attachments: List[Dict[str, Any]] = []
    for c, raw in zip(classified, attachments):
        content = raw.get("content")
        if isinstance(content, str):
            content = content.encode("utf-8", errors="ignore")
        if not isinstance(content, (bytes, bytearray)) or not content:
            c["stored_at"] = ""
            c["sha256"]    = ""
            c["size"]      = int(raw.get("size") or 0)
            evs_attachments.append({
                "filename":      c.get("filename"),
                "document_type": c.get("type"),
                "size":          c.get("size", 0),
            })
            continue
        try:
            disk_path = _save_attachment_to_shipment(
                batch_id   = out["batch_id"],
                classified = c,
                content    = bytes(content),
            )
        except Exception as exc:
            log.warning("[zc429-intake] save failed for %s: %s",
                        c.get("filename"), exc)
            c["stored_at"] = ""
            continue
        sha = hashlib.sha256(bytes(content)).hexdigest()
        c["stored_at"] = str(disk_path)
        c["sha256"]    = sha
        c["size"]      = len(content)
        stored_files.append(str(disk_path))
        # Mirror into email-evidence content-addressed store too.
        try:
            _evs.save_attachment(bytes(content),
                                 filename=c.get("filename") or "")
        except Exception:
            pass
        # Append-only lineage row. Idempotent on (event, sha, filename)
        # so reprocesses never duplicate evidence rows.
        if out["intake_event_id"]:
            try:
                lineage_id = _lineage.record_attachment(
                    intake_event_id   = out["intake_event_id"],
                    original_filename = c.get("filename") or "",
                    safe_filename     = disk_path.name,
                    sha256            = sha,
                    size              = len(content),
                    classified_type   = c.get("type", ""),
                    bucket            = c.get("bucket", ""),
                    confidence        = c.get("confidence", ""),
                    stored_path       = str(disk_path),
                    source_message_id = effective_msg_id,
                    source_sender     = sender,
                    received_at       = received_at or _now_iso(),
                )
                if lineage_id:
                    c["lineage_id"] = lineage_id
            except Exception as exc:
                log.warning("[zc429-intake] lineage record_attachment failed: %s", exc)
        evs_attachments.append({
            "filename":      c.get("filename"),
            "document_type": c.get("type"),
            "sha256":        sha,
            "size":          len(content),
        })

    out["classified"]    = classified
    out["stored_files"]  = stored_files
    out["buckets"]       = aggregate_buckets(classified)

    # 6. Email evidence — save_message + link_batch.
    evidence_msg_id = message_id or f"zc429-{out['awb']}-{out['zc_number']}"
    try:
        _evs.save_message(
            out["awb"],
            {
                "message_id":   evidence_msg_id,
                "thread_id":    f"zc429-{out['awb']}-{out['zc_number']}",
                "direction":    "incoming",
                "event_type":   "agency_zc429_received",
                "sender":       sender,
                "subject":      subject,
                "timestamp":    received_at or _now_iso(),
                "body_excerpt": (body or "")[:1000],
                "attachments":  evs_attachments,
                "matched_identifiers": {"awb": True, "mrn": True},
            },
            source="dhl_zc429_intake",
        )
        _evs.link_batch(out["awb"], out["batch_id"])
    except Exception as exc:
        log.warning("[zc429-intake] evidence store failed (non-fatal): %s", exc)

    evidence_path = str(_evs._by_awb_dir() / f"{_evs._safe_awb(out['awb'])}.json")

    # 7. Audit update — customs_declaration block.
    try:
        _update_audit(
            audit_path,
            awb              = out["awb"],
            zc_number        = out["zc_number"],
            sender           = sender,
            subject          = subject,
            received_at      = received_at or _now_iso(),
            attachment_count = len(classified),
            classified       = classified,
            evidence_path    = evidence_path,
            intake_event_id  = out["intake_event_id"],
        )
        out["audit_updated"] = True
    except Exception as exc:
        log.warning("[zc429-intake] audit update failed: %s", exc)

    # 8. Timeline event — zc429_received (existing event constant).
    try:
        tl.log_event(
            audit_path     = audit_path,
            event          = tl.EV_ZC429_RECEIVED,
            trigger_source = "dhl_zc429_intake",
            actor          = "system",
            detail         = {
                "awb":               out["awb"],
                "zc_number":         out["zc_number"],
                "sender":            sender,
                "email_subject":     subject,
                "attachment_count":  len(classified),
                "classified_counts": out["buckets"],
                "evidence_path":     evidence_path,
                "intake_event_id":   out["intake_event_id"],
                "processing_version": PROCESSING_VERSION,
            },
        )
        out["timeline_logged"] = True
    except Exception as exc:
        log.warning("[zc429-intake] timeline log failed: %s", exc)

    # 9. Append a processing note so the lineage history captures
    #    every successful processing pass (not just reprocesses).
    if out["intake_event_id"]:
        try:
            _lineage.record_processing_note(
                intake_event_id=out["intake_event_id"],
                note=f"processed: attachments={len(classified)} "
                     f"buckets={out['buckets']}",
                actor="dhl_zc429_intake",
            )
        except Exception:
            pass

    out["ok"] = True
    return out
