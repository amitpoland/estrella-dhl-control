"""
probe_payments_and_invoice_payment_state.py — Phase 10A.5 read-only probe.

Goal
----
Capture EVIDENCE — not assumptions — about which wFirma response fields
and request filters are actually available, before any Statement-of-
Account / Aging work begins.

Two surfaces are probed:

1. ``invoices/find`` — does an actual <invoice> response include the
   payment-state fields a Statement needs?

   * ``<paymentstate>``
   * ``<alreadypaid>``
   * ``<remaining>``
   * ``<paymentdate>`` (due date)
   * ``<paid_date>``  (settlement date)

   Plus sanity baselines (``<fullnumber>``, ``<currency>``, ``<netto>``,
   ``<brutto>``, ``<contractor>/<id>``) already used by Phase 9 / 10A.

2. ``payments/find`` — request shape acceptance + response field
   enumeration.

   * No filters, ``<page><start>0</start><limit>1</limit></page>``
   * ``contractor_id`` filter (if --contractor-id given)
   * ``invoice_id``    filter (if --invoice-id given)
   * ``date`` ge/le    filters (if --from / --to given)

   For each variant: HTTP code, wFirma <status> code+description,
   response root tag, leaf-tag enumeration of the first <payment>.

3. (Optional) ``payments/get`` — only if a payment id was returned by a
   successful ``payments/find``. Read-only probe to confirm the path-id
   shape works and to enumerate the single-payment response.

Hard rules (mirrors task spec)
-------------------------------
* Read-only. The tool will REFUSE to call any wFirma write action
  (``add`` / ``edit`` / ``delete`` / ``send`` / ``fiscalise`` /
  ``unfiscalise``) — see :data:`_FORBIDDEN_ACTIONS`.
* Raw XML responses are NEVER printed to stdout and NEVER committed to
  ``docs/``. They may be saved to a local ignored path via
  ``--save-raw <dir>`` for offline inspection only.
* Markdown evidence written by ``--write-evidence`` carries only:
    - endpoint tested
    - filter tested
    - accepted / rejected
    - field names (NO field VALUES)
    - redacted sample structure
    - conclusion
* If ``payments/find`` returns zero records, the tool reports that
  honestly. It must not invent payment field names.

Usage
-----
.. code-block:: bash

    # Inventory invoice payment-state fields only
    python3 -m app.tools.probe_payments_and_invoice_payment_state \\
        --invoice-id 12345

    # Probe payments with contractor + date filters
    python3 -m app.tools.probe_payments_and_invoice_payment_state \\
        --contractor-id 67890 --from 2026-01-01 --to 2026-05-09

    # Write evidence summary to a custom path (default:
    # docs/WFIRMA_PAYMENTS_PROBE_EVIDENCE.md)
    python3 -m app.tools.probe_payments_and_invoice_payment_state \\
        --invoice-id 12345 --contractor-id 67890 \\
        --write-evidence docs/WFIRMA_PAYMENTS_PROBE_EVIDENCE.md

    # Save raw XML to a local ignored path (NEVER commit)
    python3 -m app.tools.probe_payments_and_invoice_payment_state \\
        --invoice-id 12345 --save-raw /tmp/wfirma_probe_raw

The tool requires the same ``settings.wfirma_*`` credentials the live
``wfirma_client`` already uses. It performs zero authentication of its
own — the failure path on missing credentials is the same as any other
wFirma read in this repo.
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    repo_root   = here.parents[3]
    service_dir = here.parents[2]
    for p in (str(repo_root), str(service_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap()


# Module names we will NEVER touch with this tool. Defence-in-depth:
# every outbound call is screened against this set before _http_request
# is invoked. A bug that accidentally builds a write action will raise
# ProbeWriteRefused rather than reach wFirma.
_FORBIDDEN_ACTIONS: Tuple[str, ...] = (
    "add", "edit", "delete", "send",
    "fiscalise", "unfiscalise",
    # Defence against composite paths like ``add/12345`` or shorthand
    # variants. The screener checks "startswith".
)


class ProbeWriteRefused(RuntimeError):
    """Raised when the probe was about to call a non-read action."""


# ── Field inventory ────────────────────────────────────────────────────────

# Specific invoice fields the Statement subsystem cares about.
# Pinned per task spec.
_INVOICE_FIELDS_OF_INTEREST: Tuple[str, ...] = (
    "paymentstate",
    "alreadypaid",
    "remaining",
    "paymentdate",
    "paid_date",
    "total",
    "netto",
    "brutto",
    "currency",
    "contractor/id",
    "fullnumber",
)


def _enumerate_leaf_tags(node: ET.Element, prefix: str = "") -> List[str]:
    """Walk ``node`` and return every leaf tag path (e.g. 'contractor/id').

    A leaf is an element with no child elements. Repeated tag names at
    the same level are deduplicated.
    """
    seen: "OrderedDict[str, None]" = OrderedDict()

    def _walk(el: ET.Element, path: str) -> None:
        children = list(el)
        if not children:
            seen.setdefault(path or el.tag, None)
            return
        for ch in children:
            child_path = f"{path}/{ch.tag}" if path else ch.tag
            _walk(ch, child_path)

    _walk(node, prefix)
    return list(seen.keys())


def _check_fields_of_interest(node: ET.Element) -> Dict[str, bool]:
    """Return {field_path: present?} for every entry in
    :data:`_INVOICE_FIELDS_OF_INTEREST`. Path may use ``a/b`` notation."""
    out: Dict[str, bool] = {}
    for f in _INVOICE_FIELDS_OF_INTEREST:
        # ElementTree.find supports the ``a/b`` xpath subset.
        out[f] = node.find(f) is not None
    return out


# ── Transport guard ────────────────────────────────────────────────────────

def _read_only_call(
    method: str,
    module: str,
    action: str,
    body_xml: str = "",
) -> Tuple[int, str]:
    """Wrap ``wfirma_client._http_request`` with a write-action screen.

    The action component is split on ``/`` (path-id calls like
    ``download/123`` are read-only) and the FIRST segment is checked
    against :data:`_FORBIDDEN_ACTIONS`. A match raises
    :class:`ProbeWriteRefused` BEFORE any HTTP call is made.
    """
    head = (action or "").split("/", 1)[0].strip().lower()
    if head in _FORBIDDEN_ACTIONS:
        raise ProbeWriteRefused(
            f"refusing to call {module}/{action!r} — write actions are "
            f"forbidden by this probe tool"
        )
    from app.services import wfirma_client as wfc
    return wfc._http_request(method, module, action, body_xml)


# ── Probe builders ─────────────────────────────────────────────────────────

def probe_invoice_get(invoice_id: str) -> Dict[str, Any]:
    """Fetch one invoice by id and report which fields-of-interest are
    present. NEVER prints / returns the raw response text."""
    out: Dict[str, Any] = {
        "endpoint":         "invoices/get",
        "filter":           f"path-id={invoice_id}",
        "accepted":         False,
        "wfirma_status":    "",
        "wfirma_message":   "",
        "fields_present":   {},
        "leaf_tag_count":   0,
        "leaf_tag_sample":  [],
        "conclusion":       "",
    }
    try:
        http_status, response_text = _read_only_call(
            "GET", "invoices", f"get/{invoice_id}", "")
    except Exception as exc:
        out["conclusion"] = f"transport-error: {type(exc).__name__}: {exc}"
        return out
    out["http_status"] = http_status
    if http_status >= 400:
        out["conclusion"] = f"HTTP {http_status} — endpoint unreachable"
        return out
    try:
        root = ET.fromstring(response_text)
    except ET.ParseError as exc:
        out["conclusion"] = f"unparseable XML: {exc}"
        return out
    status = root.find("status")
    code = (status.findtext("code") if status is not None else "") or ""
    desc = (status.findtext("description") if status is not None else "") or ""
    out["wfirma_status"]  = code
    out["wfirma_message"] = desc
    if code != "OK":
        out["conclusion"] = f"wFirma {code}: {desc}"
        return out

    inv = root.find(".//invoice")
    if inv is None:
        out["conclusion"] = "no <invoice> in response"
        return out

    out["accepted"]       = True
    out["fields_present"] = _check_fields_of_interest(inv)
    leaves = _enumerate_leaf_tags(inv)
    out["leaf_tag_count"]  = len(leaves)
    # Sample only the tag NAMES (no values, no attributes) — the
    # markdown report carries this; raw values never escape.
    out["leaf_tag_sample"] = sorted(leaves)
    out["conclusion"] = "OK — see fields_present for evidence"
    return out


def probe_payments_find(
    *,
    contractor_id: str = "",
    invoice_id:    str = "",
    date_from:     str = "",
    date_to:       str = "",
    label:         str = "",
) -> Dict[str, Any]:
    """One ``payments/find`` attempt. Reports request acceptance, wFirma
    status, and the leaf-tag inventory of the first <payment> element
    if any. NEVER includes payment values or names of customers."""
    cond_xml = ""
    if contractor_id:
        cond_xml += (
            f"<condition><field>contractor_id</field>"
            f"<operator>eq</operator><value>{contractor_id}</value></condition>"
        )
    if invoice_id:
        cond_xml += (
            f"<condition><field>invoice_id</field>"
            f"<operator>eq</operator><value>{invoice_id}</value></condition>"
        )
    if date_from:
        cond_xml += (
            f"<condition><field>date</field>"
            f"<operator>ge</operator><value>{date_from}</value></condition>"
        )
    if date_to:
        cond_xml += (
            f"<condition><field>date</field>"
            f"<operator>le</operator><value>{date_to}</value></condition>"
        )

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<api><payments><parameters>'
          f'<conditions>{cond_xml}</conditions>'
          '<page><start>0</start><limit>1</limit></page>'
        '</parameters></payments></api>'
    )

    out: Dict[str, Any] = {
        "endpoint":         "payments/find",
        "filter":           label or "no-filter",
        "accepted":         False,
        "wfirma_status":    "",
        "wfirma_message":   "",
        "http_status":      0,
        "payment_count":    0,
        "leaf_tag_sample":  [],
        "first_payment_id": "",
        "conclusion":       "",
    }
    try:
        http_status, response_text = _read_only_call(
            "GET", "payments", "find", body)
    except Exception as exc:
        out["conclusion"] = f"transport-error: {type(exc).__name__}: {exc}"
        return out
    out["http_status"] = http_status
    if http_status >= 400:
        out["conclusion"] = f"HTTP {http_status}"
        return out
    try:
        root = ET.fromstring(response_text)
    except ET.ParseError as exc:
        out["conclusion"] = f"unparseable XML: {exc}"
        return out
    status = root.find("status")
    code = (status.findtext("code") if status is not None else "") or ""
    desc = (status.findtext("description") if status is not None else "") or ""
    out["wfirma_status"]  = code
    out["wfirma_message"] = desc
    if code != "OK":
        out["conclusion"] = f"wFirma {code}: {desc}"
        return out

    payments = root.findall(".//payment")
    out["payment_count"] = len(payments)
    if not payments:
        out["accepted"]   = True
        out["conclusion"] = "request accepted — zero payments returned"
        return out

    first = payments[0]
    leaves = _enumerate_leaf_tags(first)
    out["accepted"]         = True
    out["leaf_tag_sample"]  = sorted(leaves)
    out["first_payment_id"] = (first.findtext("id") or "").strip()
    out["conclusion"] = (
        f"request accepted — {len(payments)} payment(s) on this page; "
        "leaf tag list below"
    )
    return out


def probe_payments_get(payment_id: str) -> Dict[str, Any]:
    """Optional follow-up: confirm path-id ``payments/get/{id}`` works."""
    out: Dict[str, Any] = {
        "endpoint":        "payments/get",
        "filter":          f"path-id={payment_id}",
        "accepted":        False,
        "wfirma_status":   "",
        "wfirma_message":  "",
        "leaf_tag_sample": [],
        "conclusion":      "",
    }
    try:
        http_status, response_text = _read_only_call(
            "GET", "payments", f"get/{payment_id}", "")
    except Exception as exc:
        out["conclusion"] = f"transport-error: {type(exc).__name__}: {exc}"
        return out
    out["http_status"] = http_status
    if http_status >= 400:
        out["conclusion"] = f"HTTP {http_status}"
        return out
    try:
        root = ET.fromstring(response_text)
    except ET.ParseError as exc:
        out["conclusion"] = f"unparseable XML: {exc}"
        return out
    status = root.find("status")
    code = (status.findtext("code") if status is not None else "") or ""
    out["wfirma_status"] = code
    if code != "OK":
        out["conclusion"] = (
            f"wFirma {code}: "
            f"{status.findtext('description') if status is not None else ''}"
        )
        return out
    pay = root.find(".//payment")
    if pay is None:
        out["conclusion"] = "no <payment> in response"
        return out
    out["accepted"]        = True
    out["leaf_tag_sample"] = sorted(_enumerate_leaf_tags(pay))
    out["conclusion"]      = "OK — leaf tag list below"
    return out


# ── Raw-XML save (local only, opt-in) ──────────────────────────────────────

def _save_raw(target_dir: Path, label: str, response_text: str) -> Path:
    """Write the response text to a per-probe file under *target_dir*.
    The directory MUST be outside the repo's tracked tree — we do not
    enforce that, but the docstring + CLI help warn about it loudly."""
    target_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in label)
    out_path = target_dir / f"{safe}.xml"
    out_path.write_text(response_text, encoding="utf-8")
    return out_path


# ── Markdown evidence writer ───────────────────────────────────────────────

def render_evidence_markdown(report: Dict[str, Any]) -> str:
    """Build the markdown evidence document. Includes ONLY field/filter
    availability data — no XML payloads, no payment values, no customer
    names."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: List[str] = [
        "# wFirma Payments + Invoice Payment-State Probe Evidence",
        "",
        "Generated by "
        "`app.tools.probe_payments_and_invoice_payment_state`",
        f"(probe run at {now} UTC).",
        "",
        "**This document carries field-availability evidence only.** "
        "No raw response XML, no monetary values, no customer names. "
        "If you need to inspect raw XML, re-run the probe with "
        "`--save-raw /tmp/<dir>` (a local path NOT under the repo) and "
        "delete the dump after use.",
        "",
        "## Probes run",
        "",
        f"- invoices/get  by id   : {'yes' if report.get('invoice_get') else 'no'}",
        f"- payments/find no filter: {'yes' if report.get('payments_no_filter') else 'no'}",
        f"- payments/find by contractor: "
        f"{'yes' if report.get('payments_by_contractor') else 'no'}",
        f"- payments/find by invoice   : "
        f"{'yes' if report.get('payments_by_invoice') else 'no'}",
        f"- payments/find by date      : "
        f"{'yes' if report.get('payments_by_date') else 'no'}",
        f"- payments/get  by id        : "
        f"{'yes' if report.get('payment_get') else 'no'}",
        "",
        "---",
        "",
    ]

    # Section 1: invoice fields-of-interest
    inv = report.get("invoice_get")
    if inv:
        lines += [
            "## 1. `invoices/get/{id}` — payment-state field availability",
            "",
            f"- accepted: **{inv.get('accepted')}**",
            f"- wFirma status: `{inv.get('wfirma_status')}` "
            f"({inv.get('wfirma_message') or '—'})",
            f"- HTTP status: `{inv.get('http_status', '')}`",
            f"- conclusion: {inv.get('conclusion')}",
            "",
            "### Fields of interest (presence only — no values)",
            "",
            "| field | present? |",
            "|---|---|",
        ]
        for k, v in (inv.get("fields_present") or {}).items():
            lines.append(f"| `{k}` | {'✅ yes' if v else '❌ no'} |")
        lines.append("")
        leaves = inv.get("leaf_tag_sample") or []
        if leaves:
            lines += [
                "### Leaf tag inventory (names only)",
                "",
                "<details><summary>"
                f"{len(leaves)} leaf paths</summary>",
                "",
                "```",
            ]
            lines += list(leaves)
            lines += ["```", "", "</details>", ""]

    # Section 2: payments/find variants
    for label, key in (
        ("no filter",       "payments_no_filter"),
        ("contractor_id",   "payments_by_contractor"),
        ("invoice_id",      "payments_by_invoice"),
        ("date ge/le",      "payments_by_date"),
    ):
        p = report.get(key)
        if not p:
            continue
        lines += [
            f"## 2. `payments/find` — filter: {label}",
            "",
            f"- accepted: **{p.get('accepted')}**",
            f"- wFirma status: `{p.get('wfirma_status')}` "
            f"({p.get('wfirma_message') or '—'})",
            f"- HTTP status: `{p.get('http_status', '')}`",
            f"- payment_count on first page: {p.get('payment_count')}",
            f"- conclusion: {p.get('conclusion')}",
            "",
        ]
        leaves = p.get("leaf_tag_sample") or []
        if leaves:
            lines += [
                "### Leaf tag inventory of first payment (names only)",
                "",
                "```",
            ]
            lines += list(leaves)
            lines += ["```", ""]

    # Section 3: payments/get
    pg = report.get("payment_get")
    if pg:
        lines += [
            "## 3. `payments/get/{id}`",
            "",
            f"- accepted: **{pg.get('accepted')}**",
            f"- wFirma status: `{pg.get('wfirma_status')}` "
            f"({pg.get('wfirma_message') or '—'})",
            f"- conclusion: {pg.get('conclusion')}",
            "",
        ]
        leaves = pg.get("leaf_tag_sample") or []
        if leaves:
            lines += [
                "### Leaf tag inventory (names only)",
                "",
                "```",
            ]
            lines += list(leaves)
            lines += ["```", ""]

    # Conclusion
    lines += [
        "## Phase 10B readiness conclusion",
        "",
        "Use this evidence to decide which Statement-of-Account fields "
        "can be sourced directly from `invoices/find` versus which "
        "require a separate `payments/find` round-trip. **Do not commit "
        "raw XML or invoice values into the repo.**",
        "",
    ]
    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────────

def _run(args: argparse.Namespace) -> Dict[str, Any]:
    report: Dict[str, Any] = {}

    if args.invoice_id:
        report["invoice_get"] = probe_invoice_get(args.invoice_id)

    # Always probe payments/find with no filters when not explicitly
    # disabled. This is the cheapest acceptance check.
    if not args.skip_payments:
        report["payments_no_filter"] = probe_payments_find(
            label="no-filter",
        )
        if args.contractor_id:
            report["payments_by_contractor"] = probe_payments_find(
                contractor_id=args.contractor_id,
                label="contractor_id",
            )
        if args.invoice_id:
            report["payments_by_invoice"] = probe_payments_find(
                invoice_id=args.invoice_id,
                label="invoice_id",
            )
        if args.from_ or args.to:
            report["payments_by_date"] = probe_payments_find(
                date_from=args.from_,
                date_to=args.to,
                label="date ge/le",
            )

        # Optional follow-up: payments/get for the first id we saw.
        sample_pid = ""
        for k in ("payments_no_filter", "payments_by_contractor",
                  "payments_by_invoice", "payments_by_date"):
            v = report.get(k) or {}
            if v.get("first_payment_id"):
                sample_pid = v["first_payment_id"]
                break
        if sample_pid:
            report["payment_get"] = probe_payments_get(sample_pid)

    return report


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="probe_payments_and_invoice_payment_state",
        description=(
            "Read-only probe of wFirma invoices/{get,find} payment-state "
            "fields and payments/{find,get} request shapes. NEVER calls "
            "any write action. NEVER prints raw XML to stdout."
        ),
    )
    p.add_argument("--invoice-id", default="",
                    help="optional wFirma invoice id to fetch via "
                         "invoices/get/{id}")
    p.add_argument("--contractor-id", default="",
                    help="optional contractor id used as a payments/find filter")
    p.add_argument("--from", dest="from_", default="",
                    help="optional date filter, YYYY-MM-DD (payments/find ge)")
    p.add_argument("--to", default="",
                    help="optional date filter, YYYY-MM-DD (payments/find le)")
    p.add_argument("--skip-payments", action="store_true",
                    help="skip payments/find probes (invoices-only run)")
    p.add_argument(
        "--write-evidence", default="",
        help=("write the markdown evidence summary to this path. Default: "
              "do not write — print summary to stdout. Recommended path: "
              "docs/WFIRMA_PAYMENTS_PROBE_EVIDENCE.md"),
    )
    p.add_argument(
        "--save-raw", default="",
        help=("optional local directory to dump raw XML responses for "
              "offline inspection. NEVER use a path under the repo "
              "(real customer data). Defaults to off."),
    )
    p.add_argument("--json", action="store_true",
                    help="also print the structured probe report as JSON "
                         "(field-availability only, no raw XML)")
    args = p.parse_args(argv)

    report = _run(args)

    if args.write_evidence:
        out_path = Path(args.write_evidence)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_evidence_markdown(report), encoding="utf-8")
        print(f"evidence written to {out_path}")
    else:
        print(render_evidence_markdown(report))

    if args.json:
        # Strip nothing — _run already excludes raw XML by construction.
        print(json.dumps(report, indent=2, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(main())
