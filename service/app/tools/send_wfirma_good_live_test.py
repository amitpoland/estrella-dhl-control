"""
send_wfirma_good_live_test.py — guarded live writer for ONE good in wFirma.

Scope:
  - Creates exactly ONE good via POST goods/add.
  - Single product. No batch. No 14-product creation.
  - No PZ. No reservation. No mapping write.

Hard guards:
  1. Required flag: --live-confirm-I-understand
     (anything else → dry-run only, no HTTP call)
  2. Typed confirmation: YES_CREATE_ONE_TEST_GOOD
     (anything else → abort with rc=4, no HTTP call)
  3. Refuses if a good with the same code already exists in wFirma
     (we run goods/find first; if a good with the code exists, we abort with rc=6)
  4. The internal sender posts at most ONE request per invocation.

Schema (confirmed against a live goods/find response in this account):
    <api>
      <goods>
        <good>
          <name>...</name>
          <code>EJL/26-27/015-3</code>
          <unit>szt.</unit>
          <netto>70.41</netto>
          <type>good</type>
          <vat_code><id>222</id></vat_code>
          <vat_code_purchase><id>222</id></vat_code_purchase>
          <warehouse_type>extended</warehouse_type>
          <warehouse><id>347088</id></warehouse>
        </good>
      </goods>
    </api>

Test target (single line):
    code     EJL/26-27/015-3
    name     Wisiorek ze srebra próby 925 z diamentami laboratoryjnymi /
             SL925 Silver LGD Diamond Pendant
    netto    70.41 PLN
    unit     szt.
    vat      222 (=VAT 23%, confirmed via goods/find on existing EJL good)
    warehouse 347088 (Estrella main warehouse)

Usage:
    # Dry-run (always safe, no flag)
    python3 -m app.tools.send_wfirma_good_live_test --target ejl-015-3

    # Live (requires flag + typed confirmation)
    python3 -m app.tools.send_wfirma_good_live_test --target ejl-015-3 \\
        --live-confirm-I-understand
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    service_dir = here.parents[2]
    for p in (str(repo_root), str(service_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap()


# ── Hard-coded guards ─────────────────────────────────────────────────────────

REQUIRED_FLAG          = "--live-confirm-I-understand"
REQUIRED_CONFIRMATION  = "YES_CREATE_ONE_TEST_GOOD"
WFIRMA_GOODS_MODULE    = "goods"
WFIRMA_GOODS_ACTION    = "add"


# ── Test targets (immutable, vetted) ──────────────────────────────────────────
# Using a registry rather than free-form CLI input. Adding a target requires a
# code change + test, which is intentional friction.

@dataclass(frozen=True)
class GoodTarget:
    key:                str
    code:               str
    name:               str
    unit:               str
    netto_pln:          float
    vat_code_id:        str
    warehouse_id:       str
    warehouse_type:     str   # "simple" | "extended"
    type_value:         str   # almost always "good"


_TARGETS: Dict[str, GoodTarget] = {
    "ejl-015-3": GoodTarget(
        key            = "ejl-015-3",
        code           = "EJL/26-27/015-3",
        name           = ("Wisiorek ze srebra próby 925 z diamentami laboratoryjnymi"
                          " / SL925 Silver LGD Diamond Pendant"),
        unit           = "szt.",
        netto_pln      = 70.41,
        vat_code_id    = "222",         # VAT 23%, confirmed via live goods/find
        warehouse_id   = "347088",
        warehouse_type = "extended",
        type_value     = "good",
    ),
    "ejl-013-1": GoodTarget(
        key            = "ejl-013-1",
        code           = "EJL/26-27/013-1",
        name           = "Wisiorek ze złota próby 750 / 18KT Gold Plain Jewellery Pendant",
        unit           = "szt.",
        netto_pln      = 85.97,
        vat_code_id    = "222",
        warehouse_id   = "347088",
        warehouse_type = "extended",
        type_value     = "good",
    ),
    "ejl-013-2": GoodTarget(
        key            = "ejl-013-2",
        code           = "EJL/26-27/013-2",
        name           = "Pierścionek ze złota próby 750 / 18KT Gold Plain Jewellery Ring",
        unit           = "szt.",
        netto_pln      = 2112.31,
        vat_code_id    = "222",
        warehouse_id   = "347088",
        warehouse_type = "extended",
        type_value     = "good",
    ),
    "ejl-013-3": GoodTarget(
        key            = "ejl-013-3",
        code           = "EJL/26-27/013-3",
        name           = ("Kolczyki wkrętki z platyny próby 950 z diamentami"
                          " / PT950 Platinum Diamond Stud Earrings"),
        unit           = "szt.",
        netto_pln      = 1801.02,
        vat_code_id    = "222",
        warehouse_id   = "347088",
        warehouse_type = "extended",
        type_value     = "good",
    ),
    "ejl-014-1": GoodTarget(
        key            = "ejl-014-1",
        code           = "EJL/26-27/014-1",
        name           = "Pierścionek ze złota próby 585 z diamentami / 14KT Gold Diamond Ring",
        unit           = "szt.",
        netto_pln      = 4502.55,
        vat_code_id    = "222",
        warehouse_id   = "347088",
        warehouse_type = "extended",
        type_value     = "good",
    ),
    "ejl-015-1": GoodTarget(
        key            = "ejl-015-1",
        code           = "EJL/26-27/015-1",
        name           = ("Wisiorek ze złota próby 585 z diamentami laboratoryjnymi"
                          " / 14KT Gold LGD Diamond Pendant"),
        unit           = "szt.",
        netto_pln      = 926.45,
        vat_code_id    = "222",
        warehouse_id   = "347088",
        warehouse_type = "extended",
        type_value     = "good",
    ),
    "ejl-015-2": GoodTarget(
        key            = "ejl-015-2",
        code           = "EJL/26-27/015-2",
        name           = ("Pierścionek ze złota próby 585 z diamentami laboratoryjnymi"
                          " / 14KT Gold LGD Diamond Ring"),
        unit           = "szt.",
        netto_pln      = 578.10,
        vat_code_id    = "222",
        warehouse_id   = "347088",
        warehouse_type = "extended",
        type_value     = "good",
    ),
    "ejl-015-4": GoodTarget(
        key            = "ejl-015-4",
        code           = "EJL/26-27/015-4",
        name           = ("Pierścionek ze srebra próby 925 z diamentami laboratoryjnymi"
                          " / SL925 Silver LGD Diamond Ring"),
        unit           = "szt.",
        netto_pln      = 109.54,
        vat_code_id    = "222",
        warehouse_id   = "347088",
        warehouse_type = "extended",
        type_value     = "good",
    ),
    "ejl-015-5": GoodTarget(
        key            = "ejl-015-5",
        code           = "EJL/26-27/015-5",
        name           = "Wisiorek ze złota próby 585 z diamentami LGD / 14KT Gold LGD Stud Pendant",
        unit           = "szt.",
        netto_pln      = 346.49,
        vat_code_id    = "222",
        warehouse_id   = "347088",
        warehouse_type = "extended",
        type_value     = "good",
    ),
    "ejl-015-6": GoodTarget(
        key            = "ejl-015-6",
        code           = "EJL/26-27/015-6",
        name           = ("Kolczyki wkrętki ze złota próby 585 z diamentami LGD"
                          " / 14KT Gold LGD Diamond Stud Earrings"),
        unit           = "szt.",
        netto_pln      = 1375.22,
        vat_code_id    = "222",
        warehouse_id   = "347088",
        warehouse_type = "extended",
        type_value     = "good",
    ),
    "ejl-015-7": GoodTarget(
        key            = "ejl-015-7",
        code           = "EJL/26-27/015-7",
        name           = ("Pierścionek ze złota próby 585 z diamentami i LGD"
                          " / 14KT Gold Diamond & LGD Ring"),
        unit           = "szt.",
        netto_pln      = 949.91,
        vat_code_id    = "222",
        warehouse_id   = "347088",
        warehouse_type = "extended",
        type_value     = "good",
    ),
    "ejl-015-8": GoodTarget(
        key            = "ejl-015-8",
        code           = "EJL/26-27/015-8",
        name           = ("Kolczyki ze złota próby 585 z diamentami laboratoryjnymi"
                          " / 14KT Gold LGD Diamond Earrings"),
        unit           = "szt.",
        netto_pln      = 1234.03,
        vat_code_id    = "222",
        warehouse_id   = "347088",
        warehouse_type = "extended",
        type_value     = "good",
    ),
    "ejl-015-9": GoodTarget(
        key            = "ejl-015-9",
        code           = "EJL/26-27/015-9",
        name           = "Kolczyki ze złota próby 585 z diamentami LGD / 14KT Gold LGD Earrings",
        unit           = "szt.",
        netto_pln      = 575.81,
        vat_code_id    = "222",
        warehouse_id   = "347088",
        warehouse_type = "extended",
        type_value     = "good",
    ),
    "ejl-015-10": GoodTarget(
        key            = "ejl-015-10",
        code           = "EJL/26-27/015-10",
        name           = ("Kolczyki ze srebra próby 925 z diamentami laboratoryjnymi"
                          " / SL925 Silver LGD Diamond Earrings"),
        unit           = "szt.",
        netto_pln      = 156.87,
        vat_code_id    = "222",
        warehouse_id   = "347088",
        warehouse_type = "extended",
        type_value     = "good",
    ),
}


def list_targets() -> List[str]:
    return list(_TARGETS.keys())


def get_target(key: str) -> GoodTarget:
    if key not in _TARGETS:
        raise KeyError(f"unknown target {key!r}; known: {list_targets()}")
    return _TARGETS[key]


# ── XML payload ───────────────────────────────────────────────────────────────

def _esc(value: Any) -> str:
    return escape(str(value), {'"': "&quot;", "'": "&apos;"})


def build_good_xml(t: GoodTarget) -> str:
    """Build the goods/add payload for ONE good. No HTTP call."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <goods>
    <good>
      <name>{_esc(t.name)}</name>
      <code>{_esc(t.code)}</code>
      <unit>{_esc(t.unit)}</unit>
      <netto>{t.netto_pln:.2f}</netto>
      <type>{_esc(t.type_value)}</type>
      <vat_code>
        <id>{_esc(t.vat_code_id)}</id>
      </vat_code>
      <vat_code_purchase>
        <id>{_esc(t.vat_code_id)}</id>
      </vat_code_purchase>
      <warehouse_type>{_esc(t.warehouse_type)}</warehouse_type>
      <warehouse>
        <id>{_esc(t.warehouse_id)}</id>
      </warehouse>
    </good>
  </goods>
</api>
"""


# ── Plan + result reporting ───────────────────────────────────────────────────

def print_plan(t: GoodTarget, xml: str) -> None:
    width = 76
    print("=" * width)
    print(" wFirma GOOD — LIVE WRITE PLAN")
    print("=" * width)
    print(f"  endpoint        : POST /{WFIRMA_GOODS_MODULE}/{WFIRMA_GOODS_ACTION}")
    print(f"  target key      : {t.key}")
    print(f"  code (Indeks)   : {t.code}")
    print(f"  name            : {t.name}")
    print(f"  unit            : {t.unit}")
    print(f"  netto           : {t.netto_pln:.2f} PLN")
    print(f"  vat_code id     : {t.vat_code_id}  (= VAT 23%)")
    print(f"  warehouse_type  : {t.warehouse_type}")
    print(f"  warehouse id    : {t.warehouse_id}")
    print(f"  <type>          : {t.type_value}")
    print()
    print("  XML BODY:")
    print("  " + "-" * (width - 4))
    for line in xml.splitlines():
        print(f"  {line}")
    print("  " + "-" * (width - 4))
    print()
    print("  EXPECTED RESULT")
    print("  ---------------")
    print("  ✓ wFirma returns <status><code>OK</code></status> AND")
    print("    <goods><good><id>NNNNNNN</id></good></goods> — the new wfirma_good_id.")
    print()
    print("  ROLLBACK / DELETE INSTRUCTION")
    print("  -----------------------------")
    print("  If the good is created and you want to remove it:")
    print(f"    1. wFirma UI → Magazyn → Towary → search 'Indeks={t.code}' → ")
    print("       open the row → menu \"Usuń\". Allowed only if the good has")
    print("       no documents/movements yet (this is the case for a fresh test).")
    print(f"    2. Or via API: DELETE goods/delete/{{id}} with the same 3-header auth.")
    print(f"  If the good is created but the rest of the EJL/26-27/* set is not")
    print(f"  added yet, no harm — it sits as one orphan SKU until you decide.")
    print()


@dataclass
class GoodSendResult:
    ok:             bool
    http_status:    int
    wfirma_status:  str
    wfirma_message: str
    good_id:        Optional[str]
    raw_response:   str


def _parse_response(http_status: int, response_text: str) -> GoodSendResult:
    """Parse status + new <good><id> from goods/add response."""
    wfirma_code, wfirma_msg, good_id = "", "", None
    try:
        root = ET.fromstring(response_text)
        status = root.find("status")
        if status is not None:
            code_el = status.find("code")
            msg_el  = status.find("message")
            wfirma_code = (code_el.text or "").strip() if code_el is not None else ""
            wfirma_msg  = (msg_el.text or "").strip()  if msg_el  is not None else ""
        good_node = root.find(".//goods/good")
        if good_node is None:
            good_node = root.find(".//good")
        if good_node is not None:
            id_el = good_node.find("id")
            if id_el is not None and id_el.text:
                good_id = id_el.text.strip()
    except ET.ParseError:
        pass

    ok = http_status < 400 and wfirma_code == "OK" and good_id is not None
    return GoodSendResult(
        ok             = ok,
        http_status    = http_status,
        wfirma_status  = wfirma_code or "(empty)",
        wfirma_message = wfirma_msg,
        good_id        = good_id,
        raw_response   = response_text,
    )


def send_good(xml_body: str) -> GoodSendResult:
    """Single POST. Caller is responsible for ALL guard checks before this."""
    from app.services import wfirma_client as wfc
    http_status, response_text = wfc._http_request(
        "POST", WFIRMA_GOODS_MODULE, WFIRMA_GOODS_ACTION, xml_body,
    )
    return _parse_response(http_status, response_text)


def good_already_exists(code: str) -> Optional[str]:
    """Look up code via goods/find. Returns wfirma_id if present, else None."""
    from app.services import wfirma_client as wfc
    prod = wfc.get_product_by_code(code)
    return prod.wfirma_id if prod is not None else None


def print_result(result: GoodSendResult) -> None:
    width = 76
    print("=" * width)
    print(" wFirma GOOD — LIVE WRITE RESULT")
    print("=" * width)
    if result.ok:
        print(f"  STATUS         : ✓ OK")
        print(f"  good ID        : {result.good_id}")
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
    pass


def assert_guards(args: argparse.Namespace) -> None:
    if not args.live_confirm_I_understand:
        raise GuardError(f"Refusing to send. Required flag missing: {REQUIRED_FLAG}")


def read_confirmation(stream=None) -> str:
    s = stream if stream is not None else sys.stdin
    return s.readline().rstrip("\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None,
         input_stream=None,
         http_sender=None,
         existence_check=None) -> int:
    """
    http_sender:     callable(xml_body) → GoodSendResult (default = real POST)
    existence_check: callable(code) → Optional[str] (default = real goods/find)
    """
    p = argparse.ArgumentParser(
        prog="send_wfirma_good_live_test",
        description="GUARDED live writer for ONE good in wFirma.",
    )
    p.add_argument("--target", required=True, choices=list_targets(),
                   help="Pre-defined target key (controlled set)")
    p.add_argument(REQUIRED_FLAG, dest="live_confirm_I_understand",
                   action="store_true", help="Required for live POST")
    args = p.parse_args(argv)

    target = get_target(args.target)
    xml = build_good_xml(target)
    print_plan(target, xml)

    if not args.live_confirm_I_understand:
        print(f"DRY-RUN: flag {REQUIRED_FLAG} not set — no HTTP call made.\n")
        return 0

    try:
        assert_guards(args)
    except GuardError as exc:
        print(f"GUARD REFUSED: {exc}", file=sys.stderr)
        return 3

    # Existence pre-check — never overwrite or duplicate
    checker = existence_check if existence_check is not None else good_already_exists
    try:
        existing_id = checker(target.code)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR during existence pre-check: {exc}", file=sys.stderr)
        return 5

    if existing_id is not None:
        print(
            f"GUARD REFUSED: a good with code={target.code!r} ALREADY EXISTS "
            f"(wfirma_id={existing_id}). Refusing to send goods/add — would "
            f"create a duplicate. Use the existing id directly.",
            file=sys.stderr,
        )
        return 6

    print(
        f"You are about to create ONE REAL good in wFirma:\n"
        f"  code={target.code}  netto={target.netto_pln:.2f} PLN  warehouse={target.warehouse_id}\n"
        f"\n"
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

    sender = http_sender if http_sender is not None else send_good
    try:
        result = sender(xml)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR sending good: {exc}", file=sys.stderr)
        return 5

    print_result(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
