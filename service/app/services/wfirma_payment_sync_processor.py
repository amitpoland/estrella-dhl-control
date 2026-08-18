"""
Phase 4A — contractor payment snapshot processor.

For each contractor_id provided:
  1. Call fetch_payments_for_contractor() — READ-ONLY wFirma GET.
  2. For each <payment> node returned, insert an idempotent snapshot into
     payment_state.db (INSERT OR IGNORE on payment_id UNIQUE) and converge
     the canonical ``expense/id`` relationship onto existing rows.

Called from wfirma_webhook_scheduler._run_payment_sync_tick() and from
backfill_payment_expense_links (historical converge).
  3. Reconcile payment EXISTENCE for that contractor, but ONLY when the fetch is
     provably complete — wFirma signals payment deletion by absence, so a partial
     or failed fetch that reached the reconciler would delete valid payments.

Never raises. Never writes to customer_master, proforma_drafts, or any
business table. Never deletes a snapshot row. No Track B stage modifications.
"""
from __future__ import annotations

import json
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)


def _text(el: Optional[ET.Element]) -> Optional[str]:
    if el is None:
        return None
    v = (el.text or "").strip()
    return v if v else None


def _persist_payment_node(
    *,
    payment: ET.Element,
    payment_db: Path,
    now: str,
    contractor_id: Optional[str] = None,
) -> Optional[bool]:
    """Persist one <payment> node. Returns True=new, False=existing, None=skipped."""
    from .ledger_aggregator import _normalize_doc_link_id
    from .wfirma_payment_db import insert_payment_snapshot

    payment_id = _text(payment.find("id"))
    if not payment_id:
        return None
    cid = (contractor_id or _text(payment.find("contractor/id")) or "").strip()
    invoice_node = payment.find("invoice")
    invoice_id = _text(invoice_node.find("id")) if invoice_node is not None else None
    expense_id = _normalize_doc_link_id(payment.findtext("expense/id"))
    fields: dict = {
        "payment_id":     payment_id,
        "contractor_id":  cid,
        "invoice_id":     invoice_id,
        "expense_id":     expense_id or None,
        "payment_date":   _text(payment.find("date")),
        "value":          _text(payment.find("value")),
        "value_pln":      _text(payment.find("value_pln")),
        "currency_label": _text(payment.find("currency_label")),
        "payment_method": _text(payment.find("payment_method")),
        "payment_type":   _text(payment.find("payment_type")),
        "type":           _text(payment.find("type")),
        "notes":          _text(payment.find("notes")),
    }
    inserted = insert_payment_snapshot(
        payment_db,
        payment_id=payment_id,
        contractor_id=cid,
        invoice_id=invoice_id,
        expense_id=expense_id,
        payment_date=fields["payment_date"],
        value=fields["value"],
        value_pln=fields["value_pln"],
        currency_label=fields["currency_label"],
        payment_method=fields["payment_method"],
        payment_type=fields["payment_type"],
        type_=fields["type"],
        notes=fields["notes"],
        fetched_at=now,
        raw_json=json.dumps(fields, ensure_ascii=False),
        converge_expense_link=True,
    )
    return inserted


def sync_payments_for_contractor(
    *,
    contractor_id: str,
    payment_db: Path,
    now: str,
) -> Tuple[int, int, Optional[str]]:
    """
    Fetch all wFirma payments for one contractor, store immutable snapshots, and
    converge payment EXISTENCE (see ``reconcile_contractor_payments``).

    Returns (new_count, existing_count, error_or_None).
    Never raises.
    """
    from .wfirma_client import fetch_payments_for_contractor

    fetch_stats: Dict[str, Any] = {}
    try:
        # Empty date strings → no date filter → fetch all payments
        payment_nodes = fetch_payments_for_contractor(
            contractor_id, "", "", stats=fetch_stats
        )
    except Exception as exc:
        msg = str(exc)[:300]
        log.warning(
            "payment_sync: fetch failed contractor_id=%s: %s",
            contractor_id, msg,
        )
        return 0, 0, msg

    new_count = 0
    existing_count = 0

    for payment in payment_nodes:
        try:
            inserted = _persist_payment_node(
                payment=payment,
                payment_db=payment_db,
                now=now,
                contractor_id=contractor_id,
            )
        except Exception as exc:
            log.warning(
                "payment_sync: insert error contractor_id=%s: %s",
                contractor_id, exc,
            )
            continue
        if inserted is None:
            continue
        if inserted:
            new_count += 1
        else:
            existing_count += 1

    _reconcile_if_fetch_was_complete(
        contractor_id=contractor_id,
        payment_db=payment_db,
        payment_nodes=payment_nodes,
        fetch_stats=fetch_stats,
        now=now,
    )

    log.info(
        "payment_sync: contractor_id=%s total=%d new=%d existing=%d",
        contractor_id, new_count + existing_count, new_count, existing_count,
    )
    return new_count, existing_count, None


# The only two paginator stop reasons that mean "the collection was exhausted".
# ``safety_cap`` and ``no_new_ids`` return a PARTIAL set WITHOUT raising
# (wfirma_client._paginate_find_collection), so they must never authorise a
# tombstone — that is precisely how a transient upstream hiccup would delete
# valid payments and make AR/AP jump upward.
_COMPLETE_STOP_REASONS = frozenset({"empty", "short"})


def _reconcile_if_fetch_was_complete(
    *,
    contractor_id: str,
    payment_db: Path,
    payment_nodes: Sequence[ET.Element],
    fetch_stats: Dict[str, Any],
    now: str,
) -> Optional[dict]:
    """Tombstone/restore gate. FAIL CLOSED: reconcile only on a provably complete
    fetch, and skip silently otherwise. Returns the reconcile summary, or None
    when reconciliation was declined.

    An empty ``payment_nodes`` from a COMPLETE fetch is a legitimate result — a
    contractor whose every payment was deleted upstream reports zero, and that
    must tombstone. The failure/success distinction therefore comes from the
    error channel and the stop reason, NEVER from the row count.
    """
    from .wfirma_payment_db import reconcile_contractor_payments

    stop_reason = str(fetch_stats.get("stopped_reason") or "")
    if stop_reason not in _COMPLETE_STOP_REASONS:
        log.warning(
            "payment_sync: reconcile SKIPPED contractor_id=%s stopped_reason=%r "
            "(fetch may be partial; existing snapshots left untouched)",
            contractor_id, stop_reason or "<missing>",
        )
        return None

    live_ids = [pid for pid in (_text(n.find("id")) for n in payment_nodes) if pid]
    if len(live_ids) != len(payment_nodes):
        log.warning(
            "payment_sync: reconcile SKIPPED contractor_id=%s — %d of %d nodes "
            "had no <id>; an unidentifiable node makes the live set unreliable",
            contractor_id, len(payment_nodes) - len(live_ids), len(payment_nodes),
        )
        return None

    try:
        return reconcile_contractor_payments(
            payment_db,
            contractor_id=contractor_id,
            live_payment_ids=live_ids,
            now_iso=now,
        )
    except Exception as exc:  # never break the sync tick over reconciliation
        log.warning(
            "payment_sync: reconcile error contractor_id=%s: %s", contractor_id, exc
        )
        return None


def backfill_payment_expense_links(
    *,
    payment_db: Path,
    contractor_ids: Optional[Sequence[str]] = None,
    now: Optional[str] = None,
    checkpoint_path: Optional[Path] = None,
    limit: Optional[int] = None,
    max_retries: int = 6,
    retry_delay_s: float = 45.0,
    sleep_fn: Optional[Callable[[float], None]] = None,
    inter_delay_s: float = 0.0,
) -> Dict[str, Any]:
    """Re-fetch wFirma payments and converge expense_id onto existing snapshots.

    Read-only against wFirma. Writes only ``payment_state.db`` expense_id
    (and new snapshots if a payment appeared since last sync). Idempotent,
    resumable via ``checkpoint_path`` JSONL of completed contractor_ids.
    Does not delete snapshots. Does not bypass UNIQUE payment_id.
    """
    from .wfirma_payment_db import (
        init_payment_db,
        list_snapshot_contractor_ids,
        payment_expense_link_coverage,
    )

    init_payment_db(payment_db)
    before = payment_expense_link_coverage(payment_db)
    stamp = now or datetime.now(timezone.utc).isoformat()

    if contractor_ids is None:
        ids = list_snapshot_contractor_ids(payment_db)
    else:
        ids = [str(c).strip() for c in contractor_ids if str(c).strip()]

    done: set = _checkpoint_done_ids(checkpoint_path) if checkpoint_path else set()

    remaining = [c for c in ids if c not in done]
    if limit is not None:
        remaining = remaining[: max(0, int(limit))]

    sleeper = sleep_fn or time.sleep
    errors: List[Dict[str, str]] = []
    processed = 0
    new_total = 0
    existing_total = 0
    ok_ids: set = set()
    for cid in remaining:
        err = None
        new_count = 0
        existing_count = 0
        for attempt in range(max(0, int(max_retries)) + 1):
            new_count, existing_count, err = sync_payments_for_contractor(
                contractor_id=cid,
                payment_db=payment_db,
                now=stamp,
            )
            if not err:
                break
            if "LIMIT EXCEEDED" not in err.upper() or attempt >= int(max_retries):
                break
            delay = float(retry_delay_s) * (attempt + 1)
            log.warning(
                "payment_expense_backfill: rate-limited contractor_id=%s attempt=%d sleep=%.0fs",
                cid, attempt + 1, delay,
            )
            sleeper(delay)
        if err:
            errors.append({"contractor_id": cid, "error": err})
            log.warning("payment_expense_backfill: contractor_id=%s error=%s", cid, err)
            continue
        processed += 1
        ok_ids.add(cid)
        new_total += int(new_count)
        existing_total += int(existing_count)
        if checkpoint_path:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            with checkpoint_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "contractor_id": cid,
                    "ok": True,
                    "new": new_count,
                    "existing": existing_count,
                    "at": stamp,
                }, ensure_ascii=False) + "\n")
        if inter_delay_s:
            sleeper(float(inter_delay_s))

    after = payment_expense_link_coverage(payment_db)
    err_ids = {e["contractor_id"] for e in errors}
    if checkpoint_path and checkpoint_path.exists():
        done_after = _checkpoint_done_ids(checkpoint_path)
    else:
        done_after = set(done) | ok_ids
    result = {
        "before": before,
        "after": after,
        "contractors_planned": len(ids),
        "contractors_skipped_checkpoint": len(done),
        "contractors_attempted": len(remaining),
        "contractors_ok": processed,
        "new_snapshots": new_total,
        "existing_snapshots_seen": existing_total,
        "errors": errors,
        "failed_contractor_ids": sorted(err_ids),
        "remaining_unprocessed": [c for c in ids if c not in done_after],
    }
    log.info(
        "payment_expense_backfill: before=%s after=%s ok=%d errors=%d",
        before, after, processed, len(errors),
    )
    return result


def _checkpoint_done_ids(checkpoint_path: Path) -> set:
    done: set = set()
    if not checkpoint_path.exists():
        return done
    for line in checkpoint_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        cid = str(rec.get("contractor_id") or "").strip()
        if cid and rec.get("ok"):
            done.add(cid)
    return done


def backfill_payment_expense_links_from_period(
    *,
    payment_db: Path,
    date_to: str,
    date_from: str = "",
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Converge expense_id from the same bulk payments/find live AP uses.

    One paginated payments/find (empty lower bound, as-of ``date_to``) instead
    of per-contractor fan-out. Read-only vs wFirma. Local snapshot writes only.
    """
    from .wfirma_client import fetch_payments_for_period
    from .wfirma_payment_db import init_payment_db, payment_expense_link_coverage

    init_payment_db(payment_db)
    before = payment_expense_link_coverage(payment_db)
    stamp = now or datetime.now(timezone.utc).isoformat()
    stats: Dict[str, Any] = {}
    try:
        nodes = fetch_payments_for_period(date_from, date_to, stats=stats)
    except Exception as exc:
        msg = str(exc)[:300]
        log.warning("payment_expense_backfill_bulk: fetch failed: %s", msg)
        return {
            "before": before,
            "after": before,
            "error": msg,
            "payments_fetched": 0,
            "new_snapshots": 0,
            "existing_snapshots_seen": 0,
        }

    new_count = 0
    existing_count = 0
    skipped = 0
    persist_errors = 0
    for payment in nodes:
        try:
            inserted = _persist_payment_node(
                payment=payment,
                payment_db=payment_db,
                now=stamp,
            )
        except Exception as exc:
            persist_errors += 1
            log.warning("payment_expense_backfill_bulk: persist error: %s", exc)
            continue
        if inserted is None:
            skipped += 1
            continue
        if inserted:
            new_count += 1
        else:
            existing_count += 1

    after = payment_expense_link_coverage(payment_db)
    result = {
        "before": before,
        "after": after,
        "payments_fetched": len(nodes),
        "new_snapshots": new_count,
        "existing_snapshots_seen": existing_count,
        "skipped": skipped,
        "persist_errors": persist_errors,
        "fetch_stats": {
            "api_calls": stats.get("api_calls"),
            "pages": stats.get("pages"),
        },
        "error": None,
    }
    log.info("payment_expense_backfill_bulk: %s", result)
    return result
