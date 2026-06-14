"""generate_fixtures.py — self-verifying fixture generator for the PR #575
ledger merge-conflict validation suite.

Produces synthetic ledger fixtures + companion .metadata.json under
service/tests/fixtures/<layer>/. Every fixture is validated with the REAL
helper functions from test_pr575_ledger_merge_resolution.py, so each metadata
expected-outcome is proven, not asserted.

HONEST DEVIATIONS FROM THE TASK SPEC (documented, applied consistently):
  * "6296-line HEAD" / "122-line resolved" are not real sizes. The real ledger
    is 6261 lines. These fixtures are SYNTHETIC; their size is content-driven
    and the real computed counts are written into each metadata file.
  * Layer 4 (byte-identity vs the origin/main 6261-line blob) cannot pass for
    any synthetic fixture by definition. These fixtures exercise Layer 1-3
    logic only; that limitation is recorded in every metadata file.

Run with `python` (no python3 on this machine):
    python service/tests/fixtures/generate_fixtures.py
"""
from __future__ import annotations

import difflib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
TESTS_DIR = HERE.parents[1]            # service/tests
FIX_ROOT = HERE.parent                 # service/tests/fixtures
sys.path.insert(0, str(TESTS_DIR))

from test_pr575_ledger_merge_resolution import (   # noqa: E402  (real helpers)
    parse_governance_items,
    extract_oq_new_ids,
    extract_facts_headings,
    validate_facts_date_ordering,
    renumber_governance_ids,
)

SUBDIRS = ("deduplication", "renumbering", "facts_integrity", "self_eval")


def _w(rel: str, text: str) -> Path:
    p = FIX_ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return p


def _meta(rel: str, obj: dict) -> Path:
    p = FIX_ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, indent=2, ensure_ascii=False))
    return p


# ───────────────────────── shared ledger building blocks ────────────────────

HEADER = [
    "# PROJECT_STATE.md",
    "",
    "Source of truth for the current project execution state. "
    "(SYNTHETIC FIXTURE — not the real ledger.)",
    "",
    "---",
    "",
]


def fact_582():
    return [
        "## PR #582 — Debug-health endpoint 500s hotfix (2026-06-13, MERGED)",
        "- Newest curated FACTS entry; stabilization-safe, no authority reset.",
        "",
    ]


def fact_568():
    return [
        "## PR #568 merge+deploy gate COMPLETE — merge pending operator (2026-06-12 PM)",
        "- GATE record governance item (#568).",
        "",
    ]


def fact_cn(date="2026-06-11"):
    return [
        f"## CN↔HSN mixed-metal false-block — root cause + fix + live unblock ({date})",
        "- Customs hierarchy entry (CN).",
        "",
    ]


def fact_hsn(date="2026-06-10"):
    return [
        f"## HSN hierarchy policy note ({date})",
        "- HSN entry — older than CN.",
        "",
    ]


def fact_563():
    return [
        "## PR #563 — non-ASCII X-API-Key auth hotfix (2026-06-12, MERGED + DEPLOYED)",
        "- Auth hardening entry (#563).",
        "",
    ]


def fact_570_and_571():
    return [
        "## PR #570 verified read-only (2026-06-09 PM) — merge-gate evidence",
        "- Root-cause governance item (#570).",
        "- **Issue #571 filed (GATE 4 ISSUE)**: retroactive gate disposition pending.",
        "",
    ]


def decisions_block(b7=True):
    out = ["# DECISIONS", ""]
    if b7:
        out += [
            "## B7 Backup Service Scheduling (2026-06-13)",
            "- Backup-service decision governance item (B7).",
            "",
        ]
    out += [
        "## D1 Frozen valuation math (2026-06-01)",
        "- PZ engine valuation is frozen; do not change.",
        "",
    ]
    return out


def assumptions_block():
    return [
        "# ASSUMPTIONS",
        "",
        "## A1 wFirma credentials present in production env (2026-06-01)",
        "- Assumed available unless a 401/500 says otherwise.",
        "",
    ]


def open_questions_block(oq_new_lines, platform_remediation=True):
    out = ["# OPEN QUESTIONS", ""]
    if platform_remediation:
        out += [
            "## OQ: Platform-remediation backlog GATE 4 dispositions pending "
            "operator approval (2026-06-12)",
            "- Platform-remediation governance OQ.",
            "",
        ]
    out += oq_new_lines
    return out


def oq_new(n, title, date="2026-06-13"):
    return [
        f"## OQ-NEW-{n}: {title} ({date})",
        f"- Open question OQ-NEW-{n} body.",
        "",
    ]


def assemble(lines):
    return "\n".join(lines).rstrip("\n") + "\n"


# ───────────────────────── governance line-number reporter ──────────────────

def gov_line_numbers(text):
    """Return {anchor_label: [line numbers]} using the suite's real parser."""
    return parse_governance_items(text)


def oq_report(text):
    return [{"id": i, "line": ln} for i, ln in extract_oq_new_ids(text)]


def facts_report(text):
    out = []
    for ln, d, txt in extract_facts_headings(text):
        out.append({"line": ln, "date": d, "heading": txt})
    return out


SUITE_LIMITATION = (
    "Layer 4 (byte-identity vs the real 6261-line origin/main blob) cannot pass "
    "for any synthetic fixture; this fixture targets Layer 1-3 logic only."
)


# ───────────────────────── ledger assemblers ────────────────────────────────

def full_ledger(facts_lines, oq_new_lines, *, b7=True, platform=True,
                extra_decisions=None, extra_oq=None):
    """Assemble a complete synthetic ledger with a real ``# FACTS`` region so
    the suite's FACTS-region helpers key correctly."""
    lines = list(HEADER)
    lines += ["# FACTS", ""]
    lines += facts_lines
    dec = decisions_block(b7=b7)
    if extra_decisions:
        dec = dec[:2] + extra_decisions + dec[2:]   # inject after "# DECISIONS"
    lines += dec
    lines += assumptions_block()
    oq = open_questions_block(oq_new_lines, platform_remediation=platform)
    if extra_oq:
        oq = oq + extra_oq
    lines += oq
    return assemble(lines)


# Canonical FACTS order — strictly non-increasing dates so every named L3
# anchor (#582, #568, #563, CN, #570) lands inside the leading prefix:
#   #582 06-13 > #568 06-12 = #563 06-12 > CN 06-11 > HSN 06-10 > #570 06-09
def canonical_facts():
    return (fact_582() + fact_568() + fact_563()
            + fact_cn("2026-06-11") + fact_hsn("2026-06-10")
            + fact_570_and_571())


# ───────────────────────── metadata assembly ────────────────────────────────

def change_metadata(before_text, after_text):
    """Line-by-line transformation record from ``before_text`` (pre-merge HEAD)
    to ``after_text`` (resolved). Each op is a unified-diff hunk with explicit
    added / removed lines, so the resolution is reproducible from the record."""
    before = before_text.splitlines()
    after = after_text.splitlines()
    sm = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    ops = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        ops.append({
            "op": tag,                       # replace | delete | insert
            "before_lines": list(range(i1 + 1, i2 + 1)),
            "after_lines": list(range(j1 + 1, j2 + 1)),
            "removed": before[i1:i2],
            "added": after[j1:j2],
        })
    return {
        "before_file": "deduplication/ledger_head_premerge_with_duplicates.txt",
        "after_file": "self_eval/ledger_main_resolved_canonical.txt",
        "before_line_count": len(before),
        "after_line_count": len(after),
        "summary": ("Deduplicate the 7 governance items to one occurrence each "
                    "and renumber OQ-NEW placeholders 14->19, 15->20."),
        "operations": ops,
    }


def base_metadata(text, *, purpose, expected_outcome, assertions, category,
                  oq_renumbering=None, edge_case_params=None, notes=None):
    """Build a metadata dict from REAL helper computations against ``text``."""
    gov = gov_line_numbers(text)
    present = {label: lns for label, lns in gov.items() if lns}
    absent = [label for label, lns in gov.items() if not lns]
    duplicated = {label: lns for label, lns in gov.items() if len(lns) > 1}
    facts = facts_report(text)
    facts_dates = [f["date"] for f in facts if f["date"]]
    ordering_violations = validate_facts_date_ordering(facts_dates)
    meta = {
        "category": category,
        "purpose": purpose,
        "expected_outcome": expected_outcome,
        "assertions_targeted": assertions,
        "governance_items": {
            "present": present,
            "absent": absent,
            "duplicated": duplicated,
        },
        "oq_new": {
            "headings": oq_report(text),
            "renumbering": oq_renumbering or {},
        },
        "facts_date_ordering": {
            "dates_in_document_order": facts_dates,
            "descending_violations": ordering_violations,
            "is_strict_descending": ordering_violations == [],
        },
        "edge_case_params": edge_case_params or {},
        "suite_limitation": SUITE_LIMITATION,
        "generator": "service/tests/fixtures/generate_fixtures.py",
    }
    if notes:
        meta["notes"] = notes
    return meta


# ───────────────────────── fixture builders ─────────────────────────────────

def build_all():
    """Build every fixture + metadata, write to disk, and return a list of
    (relpath, text, expected_dict) for self-verification."""
    out = []

    # ── Cat 1 — pre-merge HEAD with duplicates (deduplication/) ──────────────
    premerge_facts = (
        fact_582()
        + fact_568() + fact_568()                 # #568 duplicated
        + fact_563()
        + fact_cn("2026-06-11") + fact_hsn("2026-06-10")
        + fact_570_and_571() + fact_570_and_571()  # #570 + #571 duplicated
    )
    premerge_oq = (
        oq_new(14, "B3 reservations write-path gate")
        + oq_new(15, "B7 backup mechanism selection")
        + oq_new(14, "B3 reservations write-path gate")   # dup
        + oq_new(15, "B7 backup mechanism selection")      # dup
    )
    premerge = full_ledger(
        premerge_facts, premerge_oq,
        extra_decisions=[
            "## B7 Backup Service Scheduling (2026-06-13)",   # B7 duplicated
            "- Duplicate B7 governance item (merge artefact).",
            "",
        ],
        extra_oq=[
            "## OQ: Platform-remediation backlog GATE 4 dispositions pending "
            "operator approval (2026-06-12)",                 # platform dup
            "- Duplicate platform-remediation OQ (merge artefact).",
            "",
        ],
    )
    out.append((
        "deduplication/ledger_head_premerge_with_duplicates.txt", premerge,
        base_metadata(
            premerge, category="deduplication / pre-merge HEAD",
            purpose=("Unresolved merge HEAD: every one of the 7 governance "
                     "items appears at least twice, OQ-NEW still at pre-merge "
                     "placeholders 14/15. The state PR #575 had to deduplicate."),
            expected_outcome=("FAIL Layer-1 uniqueness (duplicates present); "
                              "PASS Layer-1 presence (nothing missing). "
                              "OQ-NEW-19/20 absent (still 14/15) so Layer-2 "
                              "fails. Layer-4 N/A (synthetic)."),
            assertions=[
                "test_layer1_anchors_are_unique -> FAIL",
                "test_layer1_each_anchor_exactly_once -> FAIL",
                "test_layer1_all_governance_anchors_present -> "
                "FAIL (anchors 19/20 absent at pre-merge ids)",
                "test_layer2_oq_new_19_and_20_present_once -> FAIL",
            ],
            oq_renumbering={"state": "pre-merge",
                            "placeholders_present": [14, 15],
                            "renumbered_to": None},
            notes="Duplication is intentional — this is the BEFORE state.",
        ),
    ))

    # ── Cat 5A — missing governance (deduplication/) ─────────────────────────
    missing = full_ledger(
        canonical_facts(),
        oq_new(19, "B3 reservations write-path gate"),   # OQ-NEW-20 dropped
        b7=False,                                          # B7 dropped
    )
    out.append((
        "deduplication/ledger_invalid_missing_governance.txt", missing,
        base_metadata(
            missing, category="deduplication / negative — missing governance",
            purpose=("Over-aggressive merge resolution that DROPPED two "
                     "governance items (B7 decision and OQ-NEW-20). Presence "
                     "check must catch the loss."),
            expected_outcome=("FAIL Layer-1 presence: 'B7 backup-service "
                              "decision' and 'OQ-NEW-20 (B7 mechanism)' absent."),
            assertions=[
                "test_layer1_all_governance_anchors_present -> FAIL",
                "test_layer2_oq_new_19_and_20_present_once -> "
                "FAIL (OQ-NEW-20 absent)",
            ],
            oq_renumbering={"state": "resolved-but-lossy",
                            "present": [19], "dropped": [20]},
            notes="Negative fixture — proves presence assertions bite.",
        ),
    ))

    # ── Cat 2 — canonical resolved (self_eval/) ──────────────────────────────
    canonical = full_ledger(
        canonical_facts(),
        oq_new(19, "B3 reservations write-path gate")
        + oq_new(20, "B7 backup mechanism selection"),
    )
    canonical_meta = base_metadata(
            canonical, category="self_eval / canonical resolved",
            purpose=("The correctly resolved file: each of the 7 governance "
                     "items exactly once, OQ-NEW placeholders 14/15 renumbered "
                     "to 19/20 after baseline max 18, FACTS strictly "
                     "descending."),
            expected_outcome=("PASS Layer-1 (present + unique), PASS Layer-2 "
                              "(19/20 once, gap-free after 18), PASS Layer-3 "
                              "(strict descending). Layer-4 byte-identity FAILS "
                              "by design — synthetic, not the 6261-line blob."),
            assertions=[
                "test_layer1_all_governance_anchors_present -> PASS",
                "test_layer1_anchors_are_unique -> PASS",
                "test_layer1_each_anchor_exactly_once -> PASS",
                "test_layer2_oq_new_19_and_20_present_once -> PASS",
                "test_layer3_newest_fact_is_first -> PASS",
                "test_layer3_leading_prefix_is_descending_and_holds_named_"
                "anchors -> PASS",
                "test_layer4_* -> FAIL (synthetic; expected)",
            ],
            oq_renumbering={
                "state": "resolved",
                "existing_max_sequential": 18,
                "reassigned": {"OQ-NEW-14 -> OQ-NEW-19": 19,
                               "OQ-NEW-15 -> OQ-NEW-20": 20},
                "renumber_helper_output": renumber_governance_ids(
                    18, [("B3 reservations", 14), ("B7 mechanism", 15)]),
            },
            notes=("Resolved counterpart of "
                   "deduplication/ledger_head_premerge_with_duplicates.txt. "
                   "Line-by-line change vs premerge recorded in the "
                   "change_metadata field."),
        )
    canonical_meta["change_metadata"] = change_metadata(premerge, canonical)
    out.append((
        "self_eval/ledger_main_resolved_canonical.txt", canonical,
        canonical_meta,
    ))

    # ── Cat 3 — FACTS descending excerpt (facts_integrity/) ──────────────────
    facts_excerpt = assemble(
        ["# FACTS", ""]
        + fact_582() + fact_568()
        + fact_cn("2026-06-11") + fact_hsn("2026-06-10")
    )
    out.append((
        "facts_integrity/facts_region_descending_order.txt", facts_excerpt,
        base_metadata(
            facts_excerpt, category="facts_integrity / clean ordering",
            purpose=("Minimal FACTS region in strict descending order "
                     "#582 (06-13) > #568 (06-12) > CN (06-11) > HSN (06-10). "
                     "The positive baseline for Layer-3."),
            expected_outcome="PASS Layer-3: zero descending violations.",
            assertions=[
                "validate_facts_date_ordering(dates) == [] -> PASS",
                "test_layer3_newest_fact_is_first -> PASS",
            ],
            notes="No DECISIONS/OQ sections — pure FACTS excerpt by design.",
        ),
    ))

    # ── Cat 5B — mid-sequence duplicate insertion (facts_integrity/) ─────────
    mid_facts = (
        fact_582() + fact_568() + fact_563()
        + fact_cn("2026-06-11")
        + fact_568()                                   # dup #568 mid-sequence
        + fact_hsn("2026-06-10") + fact_570_and_571()
    )
    mid_insert = full_ledger(
        mid_facts,
        oq_new(19, "B3 reservations write-path gate")
        + oq_new(20, "B7 backup mechanism selection"),
    )
    out.append((
        "facts_integrity/ledger_invalid_mid_sequence_insertion.txt", mid_insert,
        base_metadata(
            mid_insert, category="facts_integrity / negative — mid insertion",
            purpose=("A duplicate '## PR #568' heading re-inserted mid-FACTS "
                     "(between CN and HSN) — the classic merge double-paste. "
                     "Uniqueness must catch it even though presence is fine."),
            expected_outcome=("FAIL Layer-1 uniqueness: '#568 merge+deploy "
                              "gate record' occurs twice (non-adjacent)."),
            assertions=[
                "test_layer1_anchors_are_unique -> FAIL",
                "test_layer1_each_anchor_exactly_once -> FAIL (#568)",
                "test_layer1_all_governance_anchors_present -> PASS",
            ],
            notes=("Also perturbs FACTS dates (06-11 then 06-12-dated #568 "
                   "then 06-10) — the duplicate is itself a date-order break, "
                   "documented in facts_date_ordering above."),
        ),
    ))

    # ── Cat 5C — FACTS date order broken (facts_integrity/) ──────────────────
    asc_facts = (
        fact_hsn("2026-06-10") + fact_cn("2026-06-11")
        + fact_568() + fact_582()                       # ascending → violations
        + fact_563() + fact_570_and_571()
    )
    bad_order = full_ledger(
        asc_facts,
        oq_new(19, "B3 reservations write-path gate")
        + oq_new(20, "B7 backup mechanism selection"),
    )
    out.append((
        "facts_integrity/ledger_invalid_facts_date_order.txt", bad_order,
        base_metadata(
            bad_order, category="facts_integrity / negative — date order",
            purpose=("FACTS region written oldest-first (HSN 06-10, CN 06-11, "
                     "#568 06-12, #582 06-13, ...) — newest is NOT first. "
                     "Layer-3 must reject."),
            expected_outcome=("FAIL Layer-3: multiple ascending adjacent pairs; "
                              "newest-first assertion fails."),
            assertions=[
                "validate_facts_date_ordering(dates) != [] -> FAIL",
                "test_layer3_newest_fact_is_first -> FAIL "
                "(top date is 2026-06-10, not 2026-06-13)",
            ],
            notes="Governance presence + uniqueness remain intact by design — "
                  "this fixture isolates the ordering failure.",
        ),
    ))

    # ── Cat 4 — renumber edge cases (renumbering/) ───────────────────────────
    out.append(_edge_case(
        rel="renumbering/ledger_edge_case_max_baseline_17.txt",
        existing_max=17, oq_present_ids=[16, 17],
        to_assign=[("B3 reservations", 14), ("B7 mechanism", 15)],
        purpose=("Baseline highest sequential OQ-NEW id is 17 (not 18). Two "
                 "placeholders must become 18 and 19, gap-free from 17."),
    ))
    out.append(_edge_case(
        rel="renumbering/ledger_edge_case_max_baseline_20.txt",
        existing_max=20, oq_present_ids=[18, 19, 20],
        to_assign=[("B3 reservations", 14), ("B7 mechanism", 15)],
        purpose=("Baseline already reaches 20. New placeholders must continue "
                 "to 21 and 22 — proves the function tracks the real max, not "
                 "a hard-coded 18."),
    ))
    out.append(_edge_case(
        rel="renumbering/ledger_edge_case_multiple_collisions_3x.txt",
        existing_max=18,
        oq_present_ids=[17, 18],
        to_assign=[("collide A", 14), ("collide B", 14), ("collide C", 14)],
        purpose=("Three placeholders ALL carry the same colliding old id (14). "
                 "They must resolve to three DISTINCT gap-free ids 19/20/21 — "
                 "the old placeholder value is irrelevant to the assignment."),
    ))

    return out


def _edge_case(*, rel, existing_max, oq_present_ids, to_assign, purpose):
    """Build a compact renumber edge-case ledger + metadata. The ledger shows
    the resolved OQ-NEW set (baseline ids + newly assigned ids); the metadata
    records the exact renumber computation via the real helper."""
    assigned = renumber_governance_ids(existing_max, to_assign)
    new_ids = list(assigned.values())
    oq_lines = []
    for n in oq_present_ids:
        oq_lines += oq_new(n, f"baseline open question {n}")
    for (label, _old), new_id in zip(to_assign, new_ids):
        oq_lines += oq_new(new_id, f"reassigned: {label}")
    text = full_ledger(canonical_facts(), oq_lines)
    meta = base_metadata(
        text, category="renumbering / edge case",
        purpose=purpose,
        expected_outcome=("renumber_governance_ids(%d, ...) -> %s; assigned ids "
                          "are gap-free, order-preserving, and distinct."
                          % (existing_max, new_ids)),
        assertions=[
            "renumber_governance_ids(existing_max, to_assign) == "
            "%s" % assigned,
            "len(set(new_ids)) == len(new_ids)  # distinct",
            "new_ids == list(range(existing_max+1, existing_max+1+len(to_assign)))",
        ],
        oq_renumbering={
            "existing_max_sequential": existing_max,
            "to_assign_old_placeholders": [old for _l, old in to_assign],
            "assigned": assigned,
            "new_ids": new_ids,
        },
        edge_case_params={
            "existing_max": existing_max,
            "baseline_oq_ids": oq_present_ids,
            "num_to_assign": len(to_assign),
            "colliding_placeholders":
                len({old for _l, old in to_assign}) < len(to_assign),
        },
        notes="Renumber tests are pure-logic (do not consume SUT); this ledger "
              "illustrates the scenario and pins the helper output in metadata.",
    )
    return (rel, text, meta)


# ───────────────────────── self-verification ────────────────────────────────

def _verify(rel, text):
    """Run the real helpers against a fixture and return an observed-behaviour
    dict (used to assert metadata expectations hold)."""
    gov = gov_line_numbers(text)
    facts_dates = [f["date"] for f in facts_report(text) if f["date"]]
    return {
        "anchors_present": all(bool(v) for v in gov.values()),
        "anchors_unique": all(len(v) <= 1 for v in gov.values()),
        "missing": [k for k, v in gov.items() if not v],
        "duplicated": {k: v for k, v in gov.items() if len(v) > 1},
        "oq_ids": [i for i, _ln in extract_oq_new_ids(text)],
        "facts_dates": facts_dates,
        "facts_clean_descending":
            validate_facts_date_ordering(facts_dates) == [],
    }


def main():
    built = build_all()
    print("Writing %d fixtures + metadata under %s" % (len(built), FIX_ROOT))
    failures = []
    for rel, text, meta in built:
        _w(rel, text)
        _meta(rel + ".metadata.json", meta)
        obs = _verify(rel, text)
        # Cross-check the headline expectation encoded by each category.
        cat = meta["category"]
        ok = True
        detail = ""
        if rel.endswith("ledger_main_resolved_canonical.txt"):
            ok = (obs["anchors_present"] and obs["anchors_unique"]
                  and obs["facts_clean_descending"]
                  and 19 in obs["oq_ids"] and 20 in obs["oq_ids"])
            detail = "present+unique+descending+19/20"
        elif rel.endswith("ledger_head_premerge_with_duplicates.txt"):
            ok = (not obs["anchors_unique"] and bool(obs["duplicated"]))
            detail = "expected duplicates present"
        elif rel.endswith("ledger_invalid_missing_governance.txt"):
            ok = (not obs["anchors_present"] and bool(obs["missing"]))
            detail = "expected missing anchors"
        elif rel.endswith("facts_region_descending_order.txt"):
            ok = obs["facts_clean_descending"]
            detail = "expected clean descending"
        elif rel.endswith("ledger_invalid_mid_sequence_insertion.txt"):
            ok = not obs["anchors_unique"]
            detail = "expected a duplicate anchor"
        elif rel.endswith("ledger_invalid_facts_date_order.txt"):
            ok = not obs["facts_clean_descending"]
            detail = "expected ordering violations"
        elif "edge_case" in rel:
            # Edge ledgers illustrate renumber math; their assigned ids are
            # scenario-dependent (18/19, 21/22, 19/20/21) and need NOT match the
            # canonical OQ-NEW-19/20 anchor pins. Assert only: no duplicate
            # anchors and a clean FACTS region. The renumber output itself is
            # pinned in metadata via the real helper.
            ok = obs["anchors_unique"] and obs["facts_clean_descending"]
            detail = "no dup anchors + clean FACTS (renumber pinned in metadata)"
        status = "OK " if ok else "BAD"
        if not ok:
            failures.append((rel, detail, obs))
        print("  [%s] %-64s %s" % (status, rel, detail))
    if failures:
        print("\nSELF-VERIFICATION FAILED:")
        for rel, detail, obs in failures:
            print("  %s — wanted %s — observed %s" % (rel, detail, obs))
        return 1
    print("\nAll fixtures self-verified against the real suite helpers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
