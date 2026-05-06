"""
wfirma_customer_sync.py — operator-triggered, dry-run-default sync of
wFirma contractors into local wfirma_customers.

Pure-data classification + paginated remote pull. No live writes from
classify_pair / plan_sync; apply_plan is the ONLY function that touches
the local DB, and it never auto-resolves a CONFLICT.

Rules (also enforced by tests):
  - INSERT       — remote row, no local row with same normalised name
  - UPDATE_FILL  — local row exists, wfirma_customer_id is empty/NULL
  - UPDATE_MATCH — local row exists, wfirma_customer_id == remote.id
                   (re-confirmation; touch updated_at, refresh
                    vat_id / country if stale)
  - CONFLICT     — local row exists with a DIFFERENT non-empty
                   wfirma_customer_id (manual reconciliation needed),
                   OR multiple remote rows share the same normalised
                   name (ambiguous join)
  - SKIP         — already-matched and identical to remote

Conflicts are NEVER auto-applied. Manual mappings (rows with
match_status='matched' and a set wfirma_customer_id) are protected
from overwrite.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import wfirma_client as wfc
from . import wfirma_db as wfdb


# ── Status constants ────────────────────────────────────────────────────────

STATUS_INSERT       = "insert"
STATUS_UPDATE_FILL  = "update_fill"
STATUS_UPDATE_MATCH = "update_match"
STATUS_CONFLICT     = "conflict"
STATUS_SKIP         = "skip"

MATCH_PENDING            = "pending"
MATCH_MATCHED            = "matched"
MATCH_MATCHED_FROM_SYNC  = "matched_from_sync"
MATCH_CONFLICT           = "conflict"

# Default page size for list_contractors_page loops. wFirma's docs show
# examples up to limit=50; conservative chunk for first implementation.
PAGE_SIZE = 50


# ── Name normalisation ──────────────────────────────────────────────────────

_WHITESPACE = re.compile(r"\s+")
_TRAILING_PUNCT = re.compile(r"[\.,;:!\?]+$")


def normalise_client_name(name: str) -> str:
    """
    Lossless-by-character (case-fold, NFKC, strip, collapse whitespace,
    drop trailing punctuation) so two near-duplicate spellings of the
    same contractor reconcile to the same key.

    Pure function — no side effects, no I/O. Called by classify_pair on
    BOTH the remote name and the local client_name before comparison.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name)).strip()
    s = _WHITESPACE.sub(" ", s)
    s = _TRAILING_PUNCT.sub("", s)
    return s.casefold()


# ── Classification ──────────────────────────────────────────────────────────

@dataclass
class RemoteRow:
    wfirma_id: str
    name:      str
    nip:       str = ""
    country:   str = ""

    @classmethod
    def from_contractor(cls, c: "wfc.WFirmaContractor") -> "RemoteRow":
        return cls(
            wfirma_id = (c.wfirma_id or "").strip(),
            name      = (c.name      or "").strip(),
            nip       = (c.nip       or "").strip(),
            country   = (c.country   or "").strip(),
        )


def classify_pair(local: Optional[Dict[str, Any]],
                  remote: RemoteRow) -> str:
    """
    Decide what should happen for a single (local, remote) pair.

    *local* is the existing wfirma_customers row dict (or None when no
    local row matches the normalised name).
    *remote* is the RemoteRow built from a wFirma contractor.

    Returns one of STATUS_INSERT / STATUS_UPDATE_FILL /
    STATUS_UPDATE_MATCH / STATUS_CONFLICT / STATUS_SKIP. Pure function.
    """
    rid = (remote.wfirma_id or "").strip()
    if not rid:
        # Defensive: a remote row with no id is unusable.
        return STATUS_SKIP

    if local is None:
        return STATUS_INSERT

    local_id = (local.get("wfirma_customer_id") or "").strip()
    if not local_id:
        return STATUS_UPDATE_FILL

    if local_id == rid:
        # Already matched; refresh-or-skip decided by whether vat_id /
        # country drifted on the remote side.
        l_vat = (local.get("vat_id")  or "").strip()
        l_cty = (local.get("country") or "").strip()
        if l_vat == remote.nip and l_cty == remote.country:
            return STATUS_SKIP
        return STATUS_UPDATE_MATCH

    # Different non-empty wfirma_customer_id on local vs remote → manual
    # reconciliation only.
    return STATUS_CONFLICT


# ── Plan + apply ────────────────────────────────────────────────────────────

def _iter_all_contractors(page_size: int = PAGE_SIZE
                          ) -> Iterable["wfc.WFirmaContractor"]:
    """
    Yield every contractor in the configured wFirma company by paging
    through contractors/find. Stops on first empty page (wFirma returns
    an empty list once start exceeds total).
    """
    start = 0
    while True:
        page = wfc.list_contractors_page(start=start, limit=page_size)
        if not page:
            return
        for c in page:
            yield c
        if len(page) < page_size:
            return
        start += page_size


def plan_sync(*, page_size: int = PAGE_SIZE,
              total_remote_override: Optional[int] = None,
              ) -> Dict[str, Any]:
    """
    Read-only plan. Pulls all remote contractors and classifies them.
    Never writes. Never resolves conflicts. Returns the four buckets +
    counts.

    *total_remote_override* is for tests; in production we count via
    the iterator length.
    """
    # Fetch remote first; tally normalised-name duplicates.
    remote_all: List[RemoteRow] = []
    name_seen: Dict[str, int] = {}
    for c in _iter_all_contractors(page_size=page_size):
        r = RemoteRow.from_contractor(c)
        if not r.wfirma_id:
            continue
        remote_all.append(r)
        nk = normalise_client_name(r.name)
        if nk:
            name_seen[nk] = name_seen.get(nk, 0) + 1

    # Build a normalised-name → local row index for fast classify.
    local_rows = wfdb.list_customers()
    local_by_norm: Dict[str, Dict[str, Any]] = {}
    for row in local_rows:
        nk = normalise_client_name(row.get("client_name") or "")
        if not nk:
            continue
        # If two local rows somehow share a normalised name, pick the
        # one with a wfirma_customer_id (more authoritative). UNIQUE on
        # client_name in the schema usually prevents this, but a
        # difference in case/punctuation can produce collisions only
        # AFTER normalisation.
        prior = local_by_norm.get(nk)
        if prior is None or not (prior.get("wfirma_customer_id") or ""):
            local_by_norm[nk] = row

    insert:       List[Dict[str, Any]] = []
    update_fill:  List[Dict[str, Any]] = []
    update_match: List[Dict[str, Any]] = []
    conflict:     List[Dict[str, Any]] = []
    skip_count = 0

    for r in remote_all:
        nk = normalise_client_name(r.name)

        # Duplicate-name detection takes precedence over any other
        # classification.
        if nk and name_seen.get(nk, 0) > 1:
            conflict.append({
                "client_name":         r.name,
                "wfirma_customer_id":  r.wfirma_id,
                "country":             r.country,
                "vat_id":              r.nip,
                "reason":              "duplicate remote names share normalised key",
                "normalised_name":     nk,
            })
            continue

        local = local_by_norm.get(nk)
        status = classify_pair(local, r)
        entry = {
            "client_name":        r.name,
            "wfirma_customer_id": r.wfirma_id,
            "country":            r.country,
            "vat_id":             r.nip,
            "normalised_name":    nk,
            "local_client_name":  (local or {}).get("client_name"),
            "local_wfirma_id":    (local or {}).get("wfirma_customer_id"),
        }
        if status == STATUS_INSERT:
            insert.append(entry)
        elif status == STATUS_UPDATE_FILL:
            update_fill.append(entry)
        elif status == STATUS_UPDATE_MATCH:
            update_match.append(entry)
        elif status == STATUS_CONFLICT:
            entry["reason"] = (
                f"local row carries different wfirma_customer_id "
                f"({(local or {}).get('wfirma_customer_id')!r}) than wFirma "
                f"({r.wfirma_id!r})"
            )
            conflict.append(entry)
        else:
            skip_count += 1

    total_remote = (total_remote_override
                    if total_remote_override is not None
                    else len(remote_all))

    return {
        "total_remote":   total_remote,
        "insert":         insert,
        "update_fill":    update_fill,
        "update_match":   update_match,
        "conflict":       conflict,
        "skip_count":     skip_count,
    }


def apply_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply the safe categories of a plan (insert / update_fill /
    update_match) to wfirma_customers. Conflicts are NEVER applied.

    Caller MUST gate this behind WFIRMA_SYNC_CUSTOMERS_ALLOWED. This
    function does not check the flag itself — its job is to do the
    writes once the route has decided to.
    """
    applied = 0
    rejected_blank: List[Dict[str, Any]] = []

    for entry in plan.get("insert", []):
        wid = (entry.get("wfirma_customer_id") or "").strip()
        if not wid:
            rejected_blank.append(entry)
            continue
        wfdb.upsert_customer(
            client_name        = entry["client_name"],
            wfirma_customer_id = wid,
            vat_id             = entry.get("vat_id") or "",
            country            = entry.get("country") or "",
            match_status       = MATCH_MATCHED_FROM_SYNC,
        )
        applied += 1

    for entry in plan.get("update_fill", []):
        wid = (entry.get("wfirma_customer_id") or "").strip()
        if not wid:
            rejected_blank.append(entry)
            continue
        # update_fill targets a row whose wfirma_customer_id is empty;
        # use the EXISTING client_name as the upsert key (NOT the
        # remote name) because the local PK has not been renamed.
        local_name = entry.get("local_client_name") or entry["client_name"]
        wfdb.upsert_customer(
            client_name        = local_name,
            wfirma_customer_id = wid,
            vat_id             = entry.get("vat_id") or "",
            country            = entry.get("country") or "",
            match_status       = MATCH_MATCHED_FROM_SYNC,
        )
        applied += 1

    for entry in plan.get("update_match", []):
        wid = (entry.get("wfirma_customer_id") or "").strip()
        if not wid:
            rejected_blank.append(entry)
            continue
        local_name = entry.get("local_client_name") or entry["client_name"]
        # Re-confirmation: keep the existing match_status (don't downgrade
        # 'matched' → 'matched_from_sync'); only refresh drifted
        # vat_id / country.
        local_row = wfdb.get_customer(local_name)
        keep_status = (local_row or {}).get("match_status") or MATCH_MATCHED
        wfdb.upsert_customer(
            client_name        = local_name,
            wfirma_customer_id = wid,
            vat_id             = entry.get("vat_id") or "",
            country            = entry.get("country") or "",
            match_status       = keep_status,
        )
        applied += 1

    return {
        "applied_count":      applied,
        "skipped_conflicts":  len(plan.get("conflict", [])),
        "rejected_blank":     rejected_blank,
    }
