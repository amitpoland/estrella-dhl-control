"""test_pr575_ledger_merge_resolution.py

Validation suite for the PR #575 merge-conflict resolution of the operational
ledger ``.claude/memory/PROJECT_STATE.md``.

WHAT THIS SUITE ACTUALLY VALIDATES (grounded against the real file, not the
original spec's stated constants — three spec figures were empirically false and
are corrected here, see "SPEC DEVIATIONS" below):

  Layer 1 — Governance-item presence / anchor-scoped uniqueness
      The 7 named governance anchors each appear EXACTLY ONCE as their own
      heading/bullet line. (Not raw-substring uniqueness — several of these
      strings also occur as in-line cross-references elsewhere; the invariant is
      one *anchor* line apiece.)

  Layer 2 — Renumber logic
      OQ-NEW-19 and OQ-NEW-20 each appear exactly once as headings, plus pure
      unit tests of a renumber function (baseline 18; 14->19, 15->20; gap-free
      incrementation; collision edge cases). Global OQ-NEW contiguity is NOT
      asserted — the real ledger legitimately carries duplicate ids (6, 13) and
      gaps (7, 10, 12) plus issue-pinned ids (396/397/401/404).

  Layer 3 — FACTS region integrity
      The newest FACTS entry (#582) is first, the top run is in non-increasing
      date order, and the named governance anchors appear in descending relative
      order with no newer-dated entry inserted between them. The FULL FACTS
      region is NOT globally date-monotonic (24 legitimate out-of-order pairs
      deeper down), so only the top run + anchor order is asserted.

  Layer 4 — Byte / content identity vs origin/main
      The subject-under-test must be content-identical to the origin/main blob
      after LF normalization (per the recorded EOL-normalization lesson: Windows
      deploys CRLF, manifest authority is LF; raw-CRLF drift must not false-
      positive). Raw byte length is reported as diagnostic.

SUBJECT UNDER TEST
  By default the subject IS the origin/main blob, so the suite PASSES out of the
  box (it proves the helpers + invariants against the known-good resolution).
  To validate a *candidate* resolution instead, point the env var at it:

      set  LEDGER_SUT_PATH=C:\\path\\to\\candidate_PROJECT_STATE.md   (cmd)
      $env:LEDGER_SUT_PATH = 'C:\\path\\to\\candidate.md'             (pwsh)
      LEDGER_SUT_PATH=/path/to/candidate.md pytest ...                (bash)

  A corrupted candidate fails with line-level diagnostics naming the first
  divergent line, dropped anchors, mis-renumbered ids, or FACTS-order breaks.

  The baseline blob ref can be overridden with LEDGER_BASELINE_REF
  (default: origin/main:.claude/memory/PROJECT_STATE.md).

SPEC DEVIATIONS (original task spec vs reality — corrected, with evidence):
  1. "match main's completed 122-line version exactly"
       -> origin/main blob is 6261 lines / 539480 bytes. 122 is impossible.
          Layer 4 pins identity to the real 6261-line blob.
  2. "7 governance items appear exactly once" (raw substring)
       -> #568 / #570 / #571 strings recur as in-line cross-references; only the
          ANCHOR line is unique. Layer 1 is anchor-scoped (user-confirmed).
  3. "renumbering ... no gaps" applied globally to OQ-NEW
       -> real ledger has duplicate OQ-NEW-6/-13 and gaps 7/10/12 by design.
          Layer 2 scopes the no-gap rule to the renumber FUNCTION (pure unit
          tests) and to the 19/20 anchors, not to the whole id space.

Run:  pytest service/tests/test_pr575_ledger_merge_resolution.py -v
This file is environment-driven and writes nothing; it is safe to run anywhere
inside a clone that has the baseline ref.
"""
from __future__ import annotations

import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

LEDGER_REL = ".claude/memory/PROJECT_STATE.md"
DEFAULT_BASELINE_REF = f"origin/main:{LEDGER_REL}"

# The 7 governance anchors PR #575 had to preserve, each as a unique anchor line.
# pattern is matched against a full line via re.match (anchored at start).
GOVERNANCE_ANCHORS: Dict[str, str] = {
    "#571 GATE-4 issue (FACTS bullet)": r"- \*\*Issue #571 filed",
    "#568 merge+deploy gate record":    r"## PR #568 ",
    "#570 verified read-only":          r"## PR #570 ",
    "B7 backup-service decision":       r"## B7 ",
    "platform-remediation OQ":          r"## OQ: Platform-remediation",
    "OQ-NEW-19 (B3 reservations)":      r"## OQ-NEW-19",
    "OQ-NEW-20 (B7 mechanism)":         r"## OQ-NEW-20",
}

# Expected file shape on origin/main (pinned facts, used for fail-fast guards).
EXPECTED_BASELINE_LINES = 6261
EXPECTED_BASELINE_BYTES = 539480


# ───────────────────────── repo / blob plumbing ─────────────────────────────

def _repo_root() -> Path:
    """Walk up from this file to the git toplevel so the suite is location-
    independent inside any clone."""
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    # Fallback to the canonical verification clone.
    return Path(r"C:\PZ-verify")


def _git_show_bytes(ref: str) -> bytes:
    """``git show <ref>`` returning raw bytes. Sets MSYS_NO_PATHCONV so the
    ``origin/main:path`` ref is not mangled by Git-bash-on-Windows (the ':' and
    '/' get rewritten otherwise, silently returning an error blob)."""
    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    env["MSYS2_ARG_CONV_EXCL"] = "*"
    proc = subprocess.run(
        ["git", "show", ref],
        cwd=str(_repo_root()),
        env=env,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git show {ref!r} failed (rc={proc.returncode}): "
            + proc.stderr.decode("utf-8", "replace").strip()
        )
    return proc.stdout


def _norm_lf(b: bytes) -> bytes:
    """Normalize CRLF/CR to LF for authority comparison (recorded EOL lesson)."""
    return b.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


# ───────────────────────── required helper functions ────────────────────────

def parse_governance_items(text: str,
                           anchors: Dict[str, str] = GOVERNANCE_ANCHORS
                           ) -> Dict[str, List[int]]:
    """HELPER 1 — locate each governance anchor.

    Returns {anchor_label: [1-based line numbers where its anchor line occurs]}.
    A correctly resolved ledger has exactly one line per anchor.
    """
    compiled = {label: re.compile(pat) for label, pat in anchors.items()}
    found: Dict[str, List[int]] = {label: [] for label in anchors}
    for idx, line in enumerate(text.splitlines(), start=1):
        for label, rx in compiled.items():
            if rx.match(line):
                found[label].append(idx)
    return found


def extract_oq_new_ids(text: str) -> List[Tuple[int, int]]:
    """HELPER 2 — extract OQ-NEW heading ids with their numeric values.

    Returns [(numeric_id, line_number)] in document order, for headings of the
    form ``## OQ-NEW-<n>...``. Issue-pinned ids (e.g. 396) are included — they
    are real headings; callers decide how to treat them.
    """
    rx = re.compile(r"^## OQ-NEW-(\d+)")
    out: List[Tuple[int, int]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        m = rx.match(line)
        if m:
            out.append((int(m.group(1)), idx))
    return out


def extract_facts_headings(text: str) -> List[Tuple[int, Optional[str], str]]:
    """Locate ``## `` headings inside the ``# FACTS`` region and pull each
    entry's own date (first ``(YYYY-MM-DD`` token on the heading line).

    Returns [(line_number, iso_date_or_None, heading_text)].
    """
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "# FACTS"), None)
    if start is None:
        return []
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^# [A-Z]", lines[j]):       # next top-level section
            end = j
            break
    date_rx = re.compile(r"\((\d{4}-\d{2}-\d{2})")
    out: List[Tuple[int, Optional[str], str]] = []
    for i in range(start + 1, end):
        ln = lines[i]
        if ln.startswith("## "):
            m = date_rx.search(ln)
            out.append((i + 1, m.group(1) if m else None, ln))
    return out


def validate_facts_date_ordering(dates: List[str]) -> List[Tuple[int, str, str]]:
    """HELPER 3 — return the list of descending-order violations in a date
    sequence. A violation is an adjacent pair where the later date is NEWER than
    the earlier one (i.e. order is not non-increasing).

    Returns [(index, earlier_date, later_date)] — empty list means clean.
    """
    violations: List[Tuple[int, str, str]] = []
    for k in range(1, len(dates)):
        if dates[k] > dates[k - 1]:
            violations.append((k, dates[k - 1], dates[k]))
    return violations


def renumber_governance_ids(existing_max: int, to_assign: List[Tuple[str, int]]
                            ) -> Dict[str, int]:
    """HELPER (renumber logic under test, Layer 2) — assign new sequential ids.

    ``existing_max`` is the highest id already in use on the sequential track
    (18 at the PR #575 baseline). ``to_assign`` is an ordered list of
    (label, old_placeholder_id) needing real ids. Each gets the next integer
    after ``existing_max``, gap-free, in input order, regardless of the old
    placeholder value (so colliding/duplicate placeholders all resolve
    distinctly). Returns {label: new_id}.
    """
    out: Dict[str, int] = {}
    nxt = existing_max + 1
    for label, _old in to_assign:
        out[label] = nxt
        nxt += 1
    return out


def build_diff_report(expected: bytes, actual: bytes, *, max_lines: int = 12
                      ) -> str:
    """HELPER 4 — human-readable byte/line diff report for Layer 4 failures."""
    if expected == actual:
        return "IDENTICAL"
    exp_lines = expected.decode("utf-8", "replace").splitlines()
    act_lines = actual.decode("utf-8", "replace").splitlines()
    parts = [
        "LEDGER CONTENT MISMATCH",
        f"  expected: {len(exp_lines)} lines / {len(expected)} bytes (LF-norm)",
        f"  actual:   {len(act_lines)} lines / {len(actual)} bytes (LF-norm)",
    ]
    shown = 0
    for i in range(max(len(exp_lines), len(act_lines))):
        e = exp_lines[i] if i < len(exp_lines) else "<EOF>"
        a = act_lines[i] if i < len(act_lines) else "<EOF>"
        if e != a:
            parts.append(f"  first divergence at line {i + 1}:")
            parts.append(f"    expected: {e[:120]!r}")
            parts.append(f"    actual:   {a[:120]!r}")
            shown += 1
            if shown >= 1:
                remaining = sum(
                    1 for j in range(i, max(len(exp_lines), len(act_lines)))
                    if (exp_lines[j] if j < len(exp_lines) else None)
                    != (act_lines[j] if j < len(act_lines) else None)
                )
                parts.append(f"  (+{remaining - 1} more differing lines)")
                break
    return "\n".join(parts)


# ───────────────────────── fixtures ─────────────────────────────────────────

@pytest.fixture(scope="session")
def baseline_bytes() -> bytes:
    ref = os.environ.get("LEDGER_BASELINE_REF", DEFAULT_BASELINE_REF)
    return _git_show_bytes(ref)


@pytest.fixture(scope="session")
def sut_bytes(baseline_bytes: bytes) -> bytes:
    """Subject under test: an external candidate file if LEDGER_SUT_PATH is set,
    otherwise the baseline blob (so the suite passes out of the box)."""
    sut_path = os.environ.get("LEDGER_SUT_PATH")
    if sut_path:
        p = Path(sut_path)
        if not p.is_file():
            pytest.fail(f"LEDGER_SUT_PATH does not point at a file: {sut_path}")
        return p.read_bytes()
    return baseline_bytes


@pytest.fixture(scope="session")
def sut_text(sut_bytes: bytes) -> str:
    return _norm_lf(sut_bytes).decode("utf-8", "replace")


# ───────────────────────── sanity guard ─────────────────────────────────────

def test_baseline_blob_is_the_real_ledger(baseline_bytes: bytes):
    """Fail fast (clear message) if the baseline ref is wrong — e.g. the MSYS
    path-mangling regression that silently returns a 3-line error blob."""
    n_lines = len(_norm_lf(baseline_bytes).decode("utf-8", "replace").splitlines())
    assert n_lines == EXPECTED_BASELINE_LINES, (
        f"baseline blob has {n_lines} lines, expected {EXPECTED_BASELINE_LINES}. "
        "Wrong ref, or git-show path mangling returned an error blob. "
        "Set LEDGER_BASELINE_REF or run inside a clone with origin/main fetched."
    )


# ───────────────────────── Layer 1 — presence / uniqueness ──────────────────

def test_layer1_all_governance_anchors_present(sut_text: str):
    found = parse_governance_items(sut_text)
    missing = [label for label, hits in found.items() if not hits]
    assert not missing, f"governance anchors DROPPED by the resolution: {missing}"


def test_layer1_anchors_are_unique(sut_text: str):
    found = parse_governance_items(sut_text)
    dupes = {label: hits for label, hits in found.items() if len(hits) > 1}
    assert not dupes, (
        "governance anchors DUPLICATED (merge double-paste): "
        + "; ".join(f"{lbl} at lines {ls}" for lbl, ls in dupes.items())
    )


@pytest.mark.parametrize("label", list(GOVERNANCE_ANCHORS))
def test_layer1_each_anchor_exactly_once(sut_text: str, label: str):
    """Per-anchor diagnostic so a failure names the exact item and its lines."""
    hits = parse_governance_items(sut_text)[label]
    assert len(hits) == 1, f"{label}: expected exactly 1 anchor line, got {hits}"


# ───────────────────────── Layer 2 — renumber logic ─────────────────────────

def test_layer2_oq_new_19_and_20_present_once(sut_text: str):
    ids = extract_oq_new_ids(sut_text)
    counts = Counter(n for n, _ in ids)
    assert counts.get(19, 0) == 1, f"OQ-NEW-19 heading count = {counts.get(19, 0)}"
    assert counts.get(20, 0) == 1, f"OQ-NEW-20 heading count = {counts.get(20, 0)}"


def test_layer2_renumber_assigns_19_and_20_after_baseline_18():
    """The PR #575 case: baseline max id is 18; two placeholders (14, 15) get
    renumbered to the next sequential ids -> 19 and 20."""
    result = renumber_governance_ids(18, [("B3-reservations", 14), ("B7-mech", 15)])
    assert result == {"B3-reservations": 19, "B7-mech": 20}


def test_layer2_renumber_is_gap_free_and_order_preserving():
    result = renumber_governance_ids(
        18, [("a", 14), ("b", 15), ("c", 16), ("d", 17)]
    )
    assert list(result.values()) == [19, 20, 21, 22]   # no gaps, input order


def test_layer2_renumber_handles_max_17_baseline():
    """Edge case from the spec: when the highest existing id is 17, the first
    new id is 18 (not 19/20)."""
    result = renumber_governance_ids(17, [("x", 1), ("y", 2), ("z", 3)])
    assert list(result.values()) == [18, 19, 20]


def test_layer2_renumber_resolves_colliding_placeholders():
    """3+ placeholders sharing the same old id still resolve to distinct, gap-
    free new ids — collisions in the OLD space must not collapse the NEW space."""
    result = renumber_governance_ids(
        18, [("p", 14), ("q", 14), ("r", 14), ("s", 14)]
    )
    assert list(result.values()) == [19, 20, 21, 22]
    assert len(set(result.values())) == 4


def test_layer2_renumber_empty_is_noop():
    assert renumber_governance_ids(18, []) == {}


# ───────────────────────── Layer 3 — FACTS region integrity ─────────────────

def test_layer3_newest_fact_is_first(sut_text: str):
    heads = extract_facts_headings(sut_text)
    assert heads, "no ## headings found in the # FACTS region"
    first_line, first_date, first_text = heads[0]
    assert "#582" in first_text, (
        f"newest FACTS entry should be PR #582, got: {first_text[:80]!r}"
    )
    assert first_date == "2026-06-13", f"#582 date = {first_date}"


def _leading_noninc_prefix(dates: List[str]) -> List[str]:
    """The maximal leading run of dates that is non-increasing."""
    prefix = list(dates[:1])
    for d in dates[1:]:
        if d > prefix[-1]:
            break
        prefix.append(d)
    return prefix


def test_layer3_leading_prefix_is_descending_and_holds_named_anchors(sut_text: str):
    """The TOP of the FACTS region is the curated, descending governance run.
    We assert the leading non-increasing prefix of dated headings is clean and
    that every named governance anchor (#582, #568, CN↔HSN, #563, #570) lives
    within it — i.e. the recent governance entries are at the top, in order,
    with no newer entry inserted between them.

    The FULL FACTS region is intentionally NOT asserted monotonic: it is
    append-mostly, so curated entries sit at the top while some campaign-
    completion entries appended at the BOTTOM also carry recent dates (e.g.
    lines ~4982/4990). Only the leading governance run is the merge concern."""
    heads = [(ln, d) for (ln, d, _t) in extract_facts_headings(sut_text) if d]
    assert heads, "no dated FACTS headings"
    dates = [d for _ln, d in heads]

    prefix = _leading_noninc_prefix(dates)
    assert validate_facts_date_ordering(prefix) == []   # clean by construction
    assert prefix[0] == "2026-06-13", f"top FACTS date = {prefix[0]} (want #582)"
    prefix_len = len(prefix)

    # locate each named anchor's index within the dated-heading list
    lines = sut_text.splitlines()
    named = {
        "#582": r"## PR #582 ",
        "#568": r"## PR #568 ",
        "CN↔HSN": r"## CN",
        "#563": r"## PR #563 ",
        "#570": r"## PR #570 ",
    }
    head_lines = [ln for ln, _d in heads]
    for label, pat in named.items():
        rx = re.compile(pat)
        anchor_line = next((i + 1 for i, l in enumerate(lines) if rx.match(l)), None)
        assert anchor_line is not None, f"named anchor {label} not found"
        assert anchor_line in head_lines, f"{label} heading carries no date"
        pos = head_lines.index(anchor_line)
        assert pos < prefix_len, (
            f"named anchor {label} (line {anchor_line}, pos {pos}) falls OUTSIDE "
            f"the descending leading prefix (len {prefix_len}) — a newer-dated "
            "entry was inserted ahead of it"
        )


def test_layer3_named_anchors_in_descending_relative_order(sut_text: str):
    """#582 -> #568 -> CN↔HSN must appear in that order with no newer-dated
    entry inserted between them (no mid-sequence insertion)."""
    lines = sut_text.splitlines()

    def line_of(pat: str) -> int:
        rx = re.compile(pat)
        for i, ln in enumerate(lines, start=1):
            if rx.match(ln):
                return i
        pytest.fail(f"anchor not found for ordering check: {pat}")

    l582 = line_of(r"## PR #582 ")
    l568 = line_of(r"## PR #568 ")
    lcn = line_of(r"## CN")
    assert l582 < l568 < lcn, (
        f"named FACTS anchors out of order: #582@{l582}, #568@{l568}, CN@{lcn}"
    )


# unit tests of the date-ordering helper itself (pure, independent of the file)

def test_helper_date_ordering_clean():
    assert validate_facts_date_ordering(
        ["2026-06-13", "2026-06-12", "2026-06-12", "2026-06-10"]
    ) == []


def test_helper_date_ordering_flags_ascending_pair():
    v = validate_facts_date_ordering(["2026-06-10", "2026-06-12"])
    assert v == [(1, "2026-06-10", "2026-06-12")]


def test_helper_date_ordering_empty_and_single():
    assert validate_facts_date_ordering([]) == []
    assert validate_facts_date_ordering(["2026-06-13"]) == []


# ───────────────────────── Layer 4 — content identity ───────────────────────

def test_layer4_lf_normalized_identity(sut_bytes: bytes, baseline_bytes: bytes):
    """Authoritative check: subject is content-identical to origin/main after
    LF normalization. CRLF-only transfer drift does not count as a mismatch
    (recorded EOL-normalization lesson)."""
    exp = _norm_lf(baseline_bytes)
    act = _norm_lf(sut_bytes)
    assert act == exp, build_diff_report(exp, act)


def test_layer4_baseline_size_pins(baseline_bytes: bytes):
    """Pin the real baseline dimensions so a future ref swap is loud, not
    silent. Raw bytes may include CRLF on a Windows checkout; assert against the
    LF-normalized form which is the authority dimension."""
    lf = _norm_lf(baseline_bytes)
    assert len(lf.splitlines()) == EXPECTED_BASELINE_LINES
    # Raw blob from git object store is LF, so byte count should match too.
    if b"\r\n" not in baseline_bytes:
        assert len(lf) == EXPECTED_BASELINE_BYTES, (
            f"LF baseline is {len(lf)} bytes, expected {EXPECTED_BASELINE_BYTES}"
        )


def test_layer4_reports_raw_vs_lf_byte_lengths(sut_bytes: bytes,
                                                baseline_bytes: bytes, capsys):
    """Diagnostic (always passes): surface raw vs LF byte lengths so an operator
    can see whether any delta is pure EOL drift vs real content change."""
    print(f"baseline raw bytes : {len(baseline_bytes)}")
    print(f"baseline LF  bytes : {len(_norm_lf(baseline_bytes))}")
    print(f"subject  raw bytes : {len(sut_bytes)}")
    print(f"subject  LF  bytes : {len(_norm_lf(sut_bytes))}")
    assert True


if __name__ == "__main__":          # convenience: `python <thisfile>` smoke run
    raise SystemExit(pytest.main([__file__, "-v"]))
