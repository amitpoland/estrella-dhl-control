"""wfirma_dictionary_cache.py — operator-facing dictionaries for the
Client Master UI.

Provides human-readable labels for wFirma technical IDs so the dashboard
can render dropdowns instead of raw-ID text inputs. Backend storage and
the wFirma API contract still use the integer/string IDs verbatim — this
module is a pure presentation layer.

Sources (in priority order)
---------------------------
1. **Baseline (hardcoded):** VAT modes (222/228/229), common currencies,
   common languages, common series shapes. These are derived from
   wFirma's published documentation and the production catalog we have
   already observed in real responses (PR #152 deep-fetch live data).
2. **Live refresh:** ``refresh_from_wfirma()`` fetches the series catalog
   from wFirma's read-only ``series/find`` endpoint and merges it on top
   of the baseline. It is the ONE shared refresh function behind all three
   trigger surfaces (startup bootstrap, the periodic scheduler step in
   ``wfirma_webhook_scheduler``, and the operator Run-Now endpoint
   ``POST /dictionaries/refresh``). The last-good catalog is persisted to
   ``series_cache.json`` under the storage root so NSSM restarts do not
   lose it; ``get_refresh_status()`` exposes the four-questions status.

Hard rule: this module NEVER calls wFirma write endpoints. It is
read-only and tolerant to wFirma being unreachable — the baseline
dictionaries are always present.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ── Series cache persistence ──────────────────────────────────────────────────
# After a successful wFirma fetch the live series catalog is written to a JSON
# file. On the NEXT process restart the file is read back before a new fetch is
# attempted so the series dropdowns are immediately populated even when wFirma
# is temporarily unreachable.

#: Maximum age (hours) before the persisted cache is considered stale and a new
#: live fetch is triggered during startup.  24 hours = once per day on average.
SERIES_CACHE_TTL_HOURS: int = 24

#: Minimum minutes between scheduled refresh ATTEMPTS (any trigger, any
#: outcome). The webhook scheduler ticks every 30 seconds and a wFirma outage
#: leaves the cache permanently "stale" — without this cooldown every tick
#: would re-poll wFirma. Applies only to the scheduled path; the operator
#: Run-Now endpoint is never cooldown-gated.
SERIES_REFRESH_RETRY_COOLDOWN_MINUTES: int = 30

_cache_file_path: Optional[Path] = None
_cache_lock = threading.Lock()


def init_series_cache(path: Path) -> None:
    """Set the file path for persistent series cache storage.

    Must be called once at startup (before ``refresh_from_wfirma``).
    Idempotent: subsequent calls update the path.
    """
    global _cache_file_path
    _cache_file_path = Path(path)


def is_cache_stale(max_age_hours: int = SERIES_CACHE_TTL_HOURS) -> bool:
    """Return True when the live cache is absent, errored, or older than
    *max_age_hours*.  Baseline source state always counts as stale."""
    fetched_at = _LIVE_CACHE.get("fetched_at")
    source_states = _LIVE_CACHE.get("source_state", {})
    if not fetched_at:
        return True
    inv_state = source_states.get("invoice_series", "baseline")
    pro_state = source_states.get("proforma_series", "baseline")
    if inv_state in ("baseline", "error") and pro_state in ("baseline", "error"):
        return True
    try:
        fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        age_hours = (
            datetime.now(timezone.utc) - fetched
        ).total_seconds() / 3600
        return age_hours >= max_age_hours
    except Exception:
        return True


def _persist_cache_to_disk() -> None:
    """Write the current live cache to disk as JSON (atomic rename).

    Non-fatal: any failure is logged as a warning and silently swallowed —
    the in-memory cache remains the authoritative source.
    """
    if _cache_file_path is None:
        return
    inv_live = _LIVE_CACHE.get("invoice_series") or []
    pro_live = _LIVE_CACHE.get("proforma_series") or []
    if not inv_live and not pro_live:
        return  # nothing worth persisting — don't overwrite a good cache with empty
    snapshot = {
        "invoice_series":  inv_live,
        "proforma_series": pro_live,
        "fetched_at":      _LIVE_CACHE.get("fetched_at"),
        "source_state":    dict(_LIVE_CACHE["source_state"]),
        "schema_version":  1,
    }
    try:
        _cache_file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = _cache_file_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        # os.replace is atomic on POSIX and overwrites on Windows (unlike
        # Path.rename which raises FileExistsError on Windows if dest exists).
        import os as _os
        _os.replace(str(tmp), str(_cache_file_path))
        log.debug("series_cache persisted to %s", _cache_file_path)
    except Exception as exc:
        log.warning("series_cache persist failed: %s", exc)


def load_cache_from_disk() -> bool:
    """Load a previously-persisted series cache from disk into ``_LIVE_CACHE``.

    Returns True if a valid cache was loaded, False otherwise.
    Non-fatal: any read/parse error returns False; caller can then
    trigger a fresh wFirma fetch.
    """
    if _cache_file_path is None or not _cache_file_path.exists():
        return False
    try:
        data = json.loads(_cache_file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("series_cache disk-load failed: %s", exc)
        return False
    inv  = data.get("invoice_series")
    pro  = data.get("proforma_series")
    fat  = data.get("fetched_at")
    sts  = data.get("source_state", {})
    if not isinstance(inv, list) or not isinstance(pro, list):
        log.warning("series_cache disk-load: unexpected shape, ignoring")
        return False
    with _cache_lock:
        _LIVE_CACHE["invoice_series"]  = inv  or None
        _LIVE_CACHE["proforma_series"] = pro  or None
        _LIVE_CACHE["fetched_at"]      = fat
        _LIVE_CACHE["source_state"].update(sts)
    log.info(
        "series_cache loaded from disk: inv=%d pro=%d fetched_at=%s",
        len(inv), len(pro), fat,
    )
    return True


# ── VAT modes ────────────────────────────────────────────────────────────────
# wFirma uses three numeric codes for the invoice VAT mode.

VAT_MODES: List[Dict[str, Any]] = [
    {"id": 222, "code": "standard",       "label": "Standard (Polish 23%)"},
    {"id": 228, "code": "reverse_charge", "label": "EU Reverse Charge"},
    {"id": 229, "code": "export_0",       "label": "Export 0%"},
]


# ── Payment methods ──────────────────────────────────────────────────────────
# The accounting method codes an operator may set on a draft / Customer Master.
# Held here beside the other enum constants so the whole commercial surface has a
# single dictionary authority (federated by commercial_lookup.CommercialLookup).
PAYMENT_METHODS: List[Dict[str, Any]] = [
    {"id": "transfer",     "label": "Bank transfer"},
    {"id": "cash",         "label": "Cash"},
    {"id": "card",         "label": "Card"},
    {"id": "compensation", "label": "Compensation"},
]


# ── Currencies ───────────────────────────────────────────────────────────────
# Locally accepted commercial currencies. The PZ engine reads NBP live rates;
# this dictionary is purely UI presentation.

CURRENCIES: List[Dict[str, Any]] = [
    {"code": "EUR", "label": "EUR · Euro"},
    {"code": "USD", "label": "USD · US Dollar"},
    {"code": "PLN", "label": "PLN · Polish Złoty"},
    {"code": "GBP", "label": "GBP · British Pound"},
    {"code": "CHF", "label": "CHF · Swiss Franc"},
    {"code": "JPY", "label": "JPY · Japanese Yen"},
]


# ── Languages ────────────────────────────────────────────────────────────────
# wFirma translation_language_id values commonly observed. Each entry pairs
# the wFirma-internal id with an operator-friendly label.
# Source: production wFirma deep-fetch responses (PR #152).

LANGUAGES: List[Dict[str, Any]] = [
    {"id": "",   "label": "— Default (use account language)"},
    {"id": "1",  "label": "Polish (Polski)"},
    {"id": "2",  "label": "English"},
    {"id": "3",  "label": "German (Deutsch)"},
    {"id": "4",  "label": "French (Français)"},
    {"id": "5",  "label": "Italian (Italiano)"},
    {"id": "6",  "label": "Spanish (Español)"},
]


# ── Invoice series ───────────────────────────────────────────────────────────
# Series IDs are wFirma account-specific. The baseline gives the operator
# a starting set with the empty option for "use account default"; the live
# refresh path can extend this with the customer's actual catalog.

INVOICE_SERIES: List[Dict[str, Any]] = [
    {"id": "", "label": "— Default series"},
]

PROFORMA_SERIES: List[Dict[str, Any]] = [
    {"id": "", "label": "— Default series"},
]


# ── Public API ───────────────────────────────────────────────────────────────


def label_for_vat_mode(mode_id: Optional[int]) -> str:
    """Return the human-readable label for a vat_mode integer."""
    if mode_id is None:
        return "—"
    for m in VAT_MODES:
        if m["id"] == int(mode_id):
            return m["label"]
    return str(mode_id)


def label_for_currency(code: Optional[str]) -> str:
    """Return the human-readable label for a currency code."""
    if not code:
        return "—"
    code = (code or "").upper()
    for c in CURRENCIES:
        if c["code"] == code:
            return c["label"]
    return code


def label_for_language(lang_id: Optional[str]) -> str:
    """Return the human-readable label for a wFirma translation_language_id."""
    if not lang_id:
        return "— Default (use account language)"
    lang_id = str(lang_id)
    for L in LANGUAGES:
        if L["id"] == lang_id:
            return L["label"]
    return f"Language #{lang_id}"


# B0 dictionary refresh 2026-05-17 — runtime in-memory cache of the live
# wFirma catalog. A refresh (startup / scheduler / operator) overwrites the
# cache; until one runs, get_dictionaries() falls back to the baseline (or
# to the disk snapshot loaded via load_cache_from_disk() at startup, so an
# NSSM restart no longer degrades to baseline).

_LIVE_CACHE: Dict[str, Any] = {
    "invoice_series":  None,   # None = not refreshed yet; list = live catalog
    "proforma_series": None,
    "fetched_at":      None,
    "source_state": {
        # Each dictionary records its current source:
        #   "baseline"   — hardcoded fallback (no refresh ever ran or live empty)
        #   "live"       — populated from a successful wFirma fetch
        #   "unavailable"— endpoint exists but returned no rows
        #   "error"      — refresh attempt failed (e.g. CONTROLLER NOT FOUND or
        #                  network error). Baseline serves as fallback.
        "invoice_series":  "baseline",
        "proforma_series": "baseline",
        "languages":       "unavailable",   # wFirma exposes no live endpoint
        "currencies":      "unavailable",   # wFirma exposes no live endpoint
        "vat_modes":       "baseline",      # not a remote catalog
    },
}


# Four-questions observability for the refresh capability (canonical status
# shape — docs/patterns/status-endpoint.md). Updated by every
# refresh_from_wfirma() run regardless of trigger; read by
# get_refresh_status(). Process-local by design: "has a refresh run in THIS
# process" is exactly what the operator needs to see after an NSSM restart.
_REFRESH_STATUS: Dict[str, Any] = {
    "last_started_at":   None,   # ISO 8601 — set at the start of every run
    "last_completed_at": None,   # ISO 8601 — set when the run finishes
    "last_trigger":      None,   # "startup" | "scheduler" | "api"
    "duration_ms":       None,
    "processed":         0,      # series rows returned by wFirma
    "created":           0,      # always 0 — cache is replaced, not inserted into
    "updated":           0,      # rows adopted into the live cache
    "skipped":           0,      # hidden / non-invoice / non-proforma rows filtered
    "errors":            0,      # 1 when the last run failed, else 0
    "last_error":        None,   # str on failure, None on success
}


def _is_visible(entry: Dict[str, str]) -> bool:
    """Filter wFirma series entries that are hidden in the operator UI."""
    vis = (entry.get("visibility") or "").strip().lower()
    return vis in ("", "visible")


def refresh_from_wfirma(trigger: str = "api") -> Dict[str, Any]:
    """Refresh of the live wFirma dictionaries — the ONE shared function
    behind all three trigger surfaces (Business Feature Completeness):

    - ``trigger="startup"``   — lifespan bootstrap in ``main.py``
    - ``trigger="scheduler"`` — periodic ``wfirma_webhook_scheduler`` step
    - ``trigger="api"``       — operator ``POST /dictionaries/refresh`` (Run Now)

    Hard rules:
    - Read-only against wFirma (only ``series/find`` today; languages and
      currencies have no live endpoint and remain on baseline).
    - Never raises. Failures are isolated per dictionary and surface in
      ``source_state`` and ``get_refresh_status()``.
    - Merges live entries on top of baseline. Baseline placeholder rows
      stay so the dropdown always has a "Default series" option.
    - On a FAILED fetch the previous live entries are kept (last-known-good)
      so an autonomous scheduled refresh hitting a transient wFirma outage
      cannot wipe a working catalog; only ``source_state`` flips to "error"
      and ``fetched_at`` keeps the age of the data actually being served.
    - Mutates the module-level ``_LIVE_CACHE`` so subsequent
      ``get_dictionaries()`` calls in the same process return the live data.
    """
    started = datetime.now(timezone.utc)
    with _cache_lock:
        _REFRESH_STATUS["last_started_at"] = started.strftime("%Y-%m-%dT%H:%M:%SZ")
        _REFRESH_STATUS["last_trigger"]    = trigger

    invoice_live:  List[Dict[str, Any]] = []
    proforma_live: List[Dict[str, Any]] = []
    invoice_state  = "baseline"
    proforma_state = "baseline"
    skipped = 0
    fetch_error: Optional[str] = None

    try:
        # Import inside the guard: even a broken wfirma_client module must
        # surface as a recorded error, never as an exception to the caller.
        from . import wfirma_client as _wfc
        all_series = _wfc.fetch_series()
    except Exception as exc:
        all_series = []
        fetch_error = f"{type(exc).__name__}: {exc}"

    if all_series:
        # Split by type. wFirma series types: normal, margin, proforma,
        # offer, spec. Invoice surfaces use normal + margin (real-invoice
        # shapes). Offer / spec series stay out — they are not invoice
        # defaults.
        for s in all_series:
            if not _is_visible(s):
                skipped += 1
                continue
            entry = {"id": s["id"], "label": s["label"], "code": s.get("code", "")}
            t = s.get("type") or ""
            if t in ("normal", "margin"):
                invoice_live.append(entry)
            elif t == "proforma":
                proforma_live.append(entry)
            else:
                skipped += 1
        invoice_state  = "live" if invoice_live  else "unavailable"
        proforma_state = "live" if proforma_live else "unavailable"
    else:
        # Endpoint returned nothing — either CONTROLLER NOT FOUND or a
        # network error. Mark error, but KEEP the previous live entries
        # (last-known-good): a scheduled refresh hitting a transient outage
        # must not wipe a working catalog. With no prior live data this is
        # a no-op and baseline serves, exactly as before. The actual capture
        # happens inside the write lock below so a concurrent successful
        # refresh cannot be overwritten with a stale pre-lock snapshot.
        invoice_state  = "error"
        proforma_state = "error"
        if fetch_error is None:
            fetch_error = "wFirma series/find returned no rows"

    # Acquire _cache_lock before mutating _LIVE_CACHE so concurrent refresh
    # calls (e.g. startup + operator dashboard request racing) cannot produce
    # a half-written cache state.  load_cache_from_disk() already holds the
    # lock on its writes; this makes refresh_from_wfirma() consistent with it.
    with _cache_lock:
        if not all_series:
            # Last-known-good capture — read and write-back under the SAME
            # lock acquisition, so a successful refresh racing this failed
            # one can never be erased by a stale snapshot.
            invoice_live  = list(_LIVE_CACHE.get("invoice_series")  or [])
            proforma_live = list(_LIVE_CACHE.get("proforma_series") or [])
        _LIVE_CACHE["invoice_series"]  = invoice_live  or None
        _LIVE_CACHE["proforma_series"] = proforma_live or None
        _LIVE_CACHE["source_state"]["invoice_series"]  = invoice_state
        _LIVE_CACHE["source_state"]["proforma_series"] = proforma_state
        if all_series:
            # Only a successful fetch may claim a new fetched_at — after a
            # failed one the kept entries are still the OLD catalog and must
            # not look freshly fetched.
            _LIVE_CACHE["fetched_at"] = started.strftime("%Y-%m-%dT%H:%M:%SZ")

        completed = datetime.now(timezone.utc)
        _REFRESH_STATUS["last_completed_at"] = completed.strftime("%Y-%m-%dT%H:%M:%SZ")
        _REFRESH_STATUS["duration_ms"] = int((completed - started).total_seconds() * 1000)
        _REFRESH_STATUS["processed"]   = len(all_series)
        _REFRESH_STATUS["updated"]     = (len(invoice_live) + len(proforma_live)) if all_series else 0
        _REFRESH_STATUS["skipped"]     = skipped
        _REFRESH_STATUS["errors"]      = 1 if fetch_error else 0
        _REFRESH_STATUS["last_error"]  = fetch_error

    # Persist to disk so NSSM restart can serve last-known-good data.
    # Non-fatal: in-memory cache is authoritative even if disk write fails.
    if invoice_state == "live" or proforma_state == "live":
        _persist_cache_to_disk()

    return get_dictionaries()


def should_attempt_scheduled_refresh(
    cooldown_minutes: int = SERIES_REFRESH_RETRY_COOLDOWN_MINUTES,
) -> bool:
    """Return True when a background scheduler tick should attempt a live
    refresh: the cache is stale AND the last refresh attempt (any trigger,
    any outcome) is older than *cooldown_minutes*.

    Cheap (in-memory only) — safe to call on every 30-second scheduler tick.
    The cooldown is what keeps the scheduled path polite: a wFirma outage
    leaves the cache permanently "stale", and without it every tick would
    re-poll wFirma.
    """
    if not is_cache_stale():
        return False
    with _cache_lock:
        last_attempt = _REFRESH_STATUS.get("last_started_at")
    if not last_attempt:
        return True
    try:
        attempted = datetime.fromisoformat(last_attempt.replace("Z", "+00:00"))
        age_minutes = (datetime.now(timezone.utc) - attempted).total_seconds() / 60
        return age_minutes >= cooldown_minutes
    except Exception:
        return True


def get_refresh_status() -> Dict[str, Any]:
    """Four-questions status snapshot for the series refresh capability
    (canonical status shape — docs/patterns/status-endpoint.md).

    1. What is the current state?  → ``healthy`` / ``running`` / ``source_state``
    2. When did it last run?       → ``last_started_at`` / ``last_completed_at`` / ``fetched_at``
    3. What happened?              → ``processed`` / ``updated`` / ``skipped`` / ``errors`` / ``last_error``
    4. Can I run it now?           → ``POST /dictionaries/refresh`` is always enabled

    Field mapping for this capability: ``processed`` = series rows returned
    by wFirma; ``updated`` = rows adopted into the live cache; ``created`` =
    always 0 (the cache is replaced atomically, nothing is inserted
    incrementally); ``skipped`` = hidden / non-invoice / non-proforma rows
    filtered out. Never raises.
    """
    with _cache_lock:
        st = dict(_REFRESH_STATUS)
        fetched_at   = _LIVE_CACHE.get("fetched_at")
        source_state = dict(_LIVE_CACHE["source_state"])
    started   = st["last_started_at"]
    completed = st["last_completed_at"]
    # Same fixed-width ISO format everywhere, so string comparison is
    # chronological. running = a run started and hasn't completed yet.
    running = bool(started and (completed is None or started > completed))
    stale = is_cache_stale()
    return {
        "healthy":                (not stale) and st["last_error"] is None,
        "running":                running,
        "last_started_at":        started,
        "last_completed_at":      completed,
        "duration_ms":            st["duration_ms"],
        "processed":              st["processed"],
        "created":                st["created"],
        "updated":                st["updated"],
        "skipped":                st["skipped"],
        "errors":                 st["errors"],
        "last_error":             st["last_error"],
        "last_trigger":           st["last_trigger"],
        "fetched_at":             fetched_at,
        "source_state":           source_state,
        "is_stale":               stale,
        "cache_ttl_hours":        SERIES_CACHE_TTL_HOURS,
        "retry_cooldown_minutes": SERIES_REFRESH_RETRY_COOLDOWN_MINUTES,
    }


def get_dictionaries() -> Dict[str, Any]:
    """Return the merged dictionary payload (baseline + any live overlay).

    Live entries (from a successful ``refresh_from_wfirma()`` call in the
    same process) overlay the baseline. ``source_state`` tells the
    operator UI whether each dictionary is live, baseline, unavailable,
    or in error.
    """
    # Build invoice_series: baseline placeholder + live entries (de-duped by id)
    inv_live  = _LIVE_CACHE.get("invoice_series")  or []
    pro_live  = _LIVE_CACHE.get("proforma_series") or []
    invoice_series  = list(INVOICE_SERIES) + [e for e in inv_live  if e["id"] not in {b["id"] for b in INVOICE_SERIES}]
    proforma_series = list(PROFORMA_SERIES) + [e for e in pro_live if e["id"] not in {b["id"] for b in PROFORMA_SERIES}]

    # Cache age / stale detection — exposed so the operator UI can show
    # how fresh the series catalog is and offer a manual refresh.
    fetched_at = _LIVE_CACHE.get("fetched_at")
    cache_age_hours: Optional[float] = None
    if fetched_at:
        try:
            fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            cache_age_hours = round(
                (datetime.now(timezone.utc) - fetched).total_seconds() / 3600, 2
            )
        except Exception:
            pass

    return {
        "vat_modes":        list(VAT_MODES),
        "payment_methods":  list(PAYMENT_METHODS),
        "currencies":       list(CURRENCIES),
        "languages":        list(LANGUAGES),
        "invoice_series":   invoice_series,
        "proforma_series":  proforma_series,
        "source":           "baseline" if not (inv_live or pro_live) else "merged",
        "source_state":     dict(_LIVE_CACHE["source_state"]),
        "fetched_at":       fetched_at,
        "cache_age_hours":  cache_age_hours,
        "is_stale":         is_cache_stale(),
        "cache_ttl_hours":  SERIES_CACHE_TTL_HOURS,
        "version":          "2026-05-17",
    }
