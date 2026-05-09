"""
send_wfirma_pz_live_test.py — guarded live writer for ONE PZ API test.

Scope:
  - Accepts exactly ONE XML payload file.
  - Sends a single POST to wFirma warehouse_document_p_z/add.
  - Creates ONE PZ in wFirma if the payload is accepted.

Hard guards (cannot be removed via env vars or runtime config):
  1. The flag MUST be exactly: --live-confirm-I-understand
     Any variation, abbreviation, env var, or default-on behaviour is refused.
  2. After the flag check, the tool prints the full plan and asks the operator
     to type EXACTLY: YES_CREATE_ONE_TEST_PZ
     Any other input — including "yes", "y", "Yes", trailing whitespace
     differences, or empty Enter — aborts with no HTTP call.
  3. No batch mode. No loop. The tool sends at most ONE request, ever.
  4. Refuses any payload with more than 1 line (single-line test only).
  5. NEVER creates a reservation, NEVER creates a good, NEVER writes a
     product mapping. The only side effect on success is one PZ document
     in wFirma's warehouse module.

Usage (REQUIRED ORDER):
    python3 -m app.tools.send_wfirma_pz_live_test \\
        outputs/wfirma_pz_payload_TEST.xml \\
        --live-confirm-I-understand

The tool will then prompt for the confirmation phrase. If you don't type
exactly YES_CREATE_ONE_TEST_PZ, the tool aborts with no HTTP call.

Dry-run (no flag):
    python3 -m app.tools.send_wfirma_pz_live_test outputs/wfirma_pz_payload_TEST.xml
    → prints plan + XML, then EXITS without sending. Always safe.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    service_dir = here.parents[2]
    for p in (str(repo_root), str(service_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap()


# ── Hard-coded guards (intentionally not configurable) ────────────────────────

REQUIRED_FLAG          = "--live-confirm-I-understand"
REQUIRED_CONFIRMATION  = "YES_CREATE_ONE_TEST_PZ"
WFIRMA_PZ_MODULE       = "warehouse_document_p_z"
WFIRMA_PZ_ACTION       = "add"
MAX_LINES_FOR_TEST     = 1


# ── Plan extraction (read-only XML inspection) ────────────────────────────────

@dataclass
class PzPlan:
    endpoint:     str
    supplier_id:  str
    warehouse_id: str
    description:  str
    date:         str
    line_count:   int
    total_net:    float
    product_codes: List[str]
    xml_body:     str


def extract_plan(xml_path: Path) -> PzPlan:
    """Parse the candidate XML payload and pull a summary.

    Raises ValueError if the XML is malformed or missing required fields.
    """
    if not xml_path.is_file():
        raise FileNotFoundError(f"XML payload not found: {xml_path}")

    xml_body = xml_path.read_text(encoding="utf-8")
    try:
        root = ET.fromstring(xml_body)
    except ET.ParseError as exc:
        raise ValueError(f"XML is not well-formed: {exc}") from exc

    # Wrapper is now the umbrella plural <warehouse_documents>. Older payloads
    # used the typed <warehouse_document_p_z> wrapper; accept both for back-compat.
    wrapper = root.find("warehouse_documents") or root.find(WFIRMA_PZ_MODULE)
    if wrapper is None:
        raise ValueError(
            f"Expected wrapper <warehouse_documents> or <{WFIRMA_PZ_MODULE}> not found"
        )

    doc = wrapper.find("warehouse_document")
    if doc is None:
        raise ValueError("Missing <warehouse_document>")

    def _txt(parent: ET.Element, *path: str) -> str:
        cur: Optional[ET.Element] = parent
        for tag in path:
            if cur is None:
                return ""
            cur = cur.find(tag)
        return (cur.text or "").strip() if cur is not None else ""

    supplier_id  = _txt(doc, "contractor", "id")
    warehouse_id = _txt(doc, "warehouse", "id")
    date         = _txt(doc, "date")
    description  = _txt(doc, "description")

    contents = doc.find("warehouse_document_contents")
    line_nodes = contents.findall("warehouse_document_content") if contents is not None else []

    product_codes: List[str] = []
    total_net = 0.0
    for line in line_nodes:
        # PZ XML now references existing goods by <good><id>. Display the id;
        # the human-readable line label is in <name> (line-level, not the
        # good's master-record name).
        good_id = _txt(line, "good", "id")
        line_name = _txt(line, "name")
        if good_id:
            product_codes.append(f"good_id={good_id} ({line_name})" if line_name else f"good_id={good_id}")
        else:
            product_codes.append("(missing good_id)")
        try:
            qty = float(_txt(line, "unit_count") or 0)
        except ValueError:
            qty = 0.0
        try:
            price = float(_txt(line, "price") or 0)
        except ValueError:
            price = 0.0
        total_net += qty * price

    if not supplier_id:
        raise ValueError("Missing <contractor><id>")
    if not warehouse_id:
        raise ValueError("Missing <warehouse><id>")
    if not date:
        raise ValueError("Missing <date>")
    if not line_nodes:
        raise ValueError("No <warehouse_document_content> entries — refusing to send empty PZ")

    return PzPlan(
        endpoint     = f"POST /{WFIRMA_PZ_MODULE}/{WFIRMA_PZ_ACTION}",
        supplier_id  = supplier_id,
        warehouse_id = warehouse_id,
        description  = description,
        date         = date,
        line_count   = len(line_nodes),
        total_net    = round(total_net, 2),
        product_codes = product_codes,
        xml_body     = xml_body,
    )


def print_plan(plan: PzPlan) -> None:
    width = 76
    print("=" * width)
    print(" wFirma PZ — LIVE WRITE PLAN")
    print("=" * width)
    print(f"  endpoint     : {plan.endpoint}")
    print(f"  supplier ID  : {plan.supplier_id}")
    print(f"  warehouse ID : {plan.warehouse_id}")
    print(f"  date         : {plan.date}")
    print(f"  description  : {plan.description}")
    print(f"  line count   : {plan.line_count}")
    print(f"  total net    : {plan.total_net:,.2f} PLN")
    print(f"  product codes: {', '.join(plan.product_codes)}")
    print()
    print("  XML BODY:")
    print("  " + "-" * (width - 4))
    for line in plan.xml_body.splitlines():
        print(f"  {line}")
    print("  " + "-" * (width - 4))
    print()


# ── Send + response parsing ───────────────────────────────────────────────────

@dataclass
class PzSendResult:
    ok:             bool
    http_status:    int
    wfirma_status:  str
    wfirma_message: str
    document_id:    Optional[str]
    raw_response:   str


def _parse_response(http_status: int, response_text: str) -> PzSendResult:
    """Pull the wFirma envelope status + new document ID (if any)."""
    wfirma_code, wfirma_msg = "", ""
    document_id: Optional[str] = None

    try:
        root = ET.fromstring(response_text)
        status = root.find("status")
        if status is not None:
            code_el = status.find("code")
            msg_el  = status.find("message")
            wfirma_code = (code_el.text or "").strip() if code_el is not None else ""
            wfirma_msg  = (msg_el.text or "").strip()  if msg_el  is not None else ""
        wd_node = root.find(f".//{WFIRMA_PZ_MODULE}/warehouse_document")
        if wd_node is None:
            wd_node = root.find(".//warehouse_document")
        if wd_node is not None:
            id_el = wd_node.find("id")
            if id_el is not None and id_el.text:
                document_id = id_el.text.strip()
    except ET.ParseError:
        pass

    ok = http_status < 400 and wfirma_code == "OK" and document_id is not None
    return PzSendResult(
        ok             = ok,
        http_status    = http_status,
        wfirma_status  = wfirma_code or "(empty)",
        wfirma_message = wfirma_msg,
        document_id    = document_id,
        raw_response   = response_text,
    )


def send_pz(xml_body: str) -> PzSendResult:
    """Single POST. Caller is responsible for ALL guard checks before this."""
    from app.services import wfirma_client as wfc

    http_status, response_text = wfc._http_request(
        "POST", WFIRMA_PZ_MODULE, WFIRMA_PZ_ACTION, xml_body,
    )
    return _parse_response(http_status, response_text)


def print_result(result: PzSendResult) -> None:
    width = 76
    print("=" * width)
    print(" wFirma PZ — LIVE WRITE RESULT")
    print("=" * width)
    if result.ok:
        print(f"  STATUS         : ✓ OK")
        print(f"  document ID    : {result.document_id}")
    else:
        print(f"  STATUS         : ✗ FAILED")
        print(f"  http_status    : {result.http_status}")
        print(f"  wfirma_status  : {result.wfirma_status}")
        if result.wfirma_message:
            print(f"  wfirma_message : {result.wfirma_message}")
    print()
    print("  RAW RESPONSE:")
    print("  " + "-" * (width - 4))
    for line in result.raw_response.splitlines():
        print(f"  {line}")
    print("  " + "-" * (width - 4))
    print()


# ── Guards ────────────────────────────────────────────────────────────────────

class GuardError(Exception):
    """Raised when a safety guard refuses to proceed."""


def assert_guards(args: argparse.Namespace, plan: PzPlan) -> None:
    """Strict pre-send checks. Any failure raises GuardError — no HTTP."""
    if not args.live_confirm_I_understand:
        raise GuardError(
            f"Refusing to send. Required flag is missing: {REQUIRED_FLAG}\n"
            f"This tool will only send a live PZ when the operator explicitly "
            f"types the flag. Dry-run (no flag) is always safe."
        )
    if plan.line_count > MAX_LINES_FOR_TEST:
        raise GuardError(
            f"Refusing to send: payload has {plan.line_count} lines but live test "
            f"is restricted to {MAX_LINES_FOR_TEST} line. Use a single-line PZ_READY "
            f"and rebuild the XML."
        )
    if plan.line_count < 1:
        raise GuardError("Refusing to send: empty payload.")


def read_confirmation(stream=None) -> str:
    """Prompt and read confirmation from operator. Stream injectable for tests."""
    s = stream if stream is not None else sys.stdin
    return s.readline().rstrip("\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None,
         input_stream=None,
         http_sender=None) -> int:
    """
    argv         : process args (None = sys.argv[1:])
    input_stream : injected stdin replacement (for tests)
    http_sender  : optional callable(xml_body) → PzSendResult (for tests).
                   Default = real wFirma POST.
    """
    p = argparse.ArgumentParser(
        prog="send_wfirma_pz_live_test",
        description="GUARDED live writer for ONE PZ in wFirma.",
    )
    p.add_argument("xml_path", help="Path to candidate XML payload (single-line only)")
    p.add_argument(
        REQUIRED_FLAG,
        dest="live_confirm_I_understand",
        action="store_true",
        help="Required flag — without it, the tool only prints the plan.",
    )
    args = p.parse_args(argv)

    xml_path = Path(args.xml_path).expanduser()

    try:
        plan = extract_plan(xml_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print_plan(plan)

    if not args.live_confirm_I_understand:
        print(f"DRY-RUN: flag {REQUIRED_FLAG} not set — no HTTP call made.\n")
        return 0

    try:
        assert_guards(args, plan)
    except GuardError as exc:
        print(f"GUARD REFUSED: {exc}", file=sys.stderr)
        return 3

    print(
        f"You are about to create a REAL PZ in wFirma.\n"
        f"To proceed, type exactly the following phrase and press Enter.\n"
        f"Anything else aborts with no HTTP call.\n\n"
        f"  Required phrase: {REQUIRED_CONFIRMATION}\n"
    )
    print("> ", end="", flush=True)
    typed = read_confirmation(input_stream)

    if typed != REQUIRED_CONFIRMATION:
        print(
            f"\nABORTED — confirmation phrase did not match.\n"
            f"  expected: {REQUIRED_CONFIRMATION!r}\n"
            f"  received: {typed!r}\n"
            f"No HTTP call was made.",
            file=sys.stderr,
        )
        return 4

    print("\nConfirmation accepted. Sending ONE POST to wFirma…\n")

    sender = http_sender if http_sender is not None else send_pz
    try:
        result = sender(plan.xml_body)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR sending PZ: {exc}", file=sys.stderr)
        return 5

    print_result(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
