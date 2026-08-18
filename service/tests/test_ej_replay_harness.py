"""
test_ej_replay_harness.py — safety tests for the replay certification harness.

The harness is operational verification tooling, not an application module. Its
ONLY load-bearing property is that it can never mutate live storage. These tests
pin that property and the six safety gates.

Scope note: these tests exercise the harness's own primitives against temporary
fixture directories. They never touch service/app/storage, never import the
application, and make no network call.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

HARNESS_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ej_replay_harness.py"

V1_SOURCE_SHA256 = "4079c621c63fde4e0bb7b1261db86d6eb3a4827b4103f3169123cca3ffbcddc7"


def _load_harness():
    """Import the harness by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("ej_replay_harness", HARNESS_PATH)
    assert spec and spec.loader, "harness spec could not be created"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ej_replay_harness"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def H():
    return _load_harness()


@pytest.fixture()
def fixture_storage(tmp_path: Path) -> Path:
    """A realistic miniature storage root: SQLite DBs (WAL), JSON, and dirs."""
    root = tmp_path / "live_storage"
    root.mkdir()
    for name in ("packing.db", "documents.db", "master_audit.sqlite"):
        con = sqlite3.connect(root / name)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        con.execute("INSERT INTO t (v) VALUES ('seed')")
        con.commit()
        con.close()
    (root / "version.json").write_text('{"v": 1}', encoding="utf-8")
    (root / "outputs").mkdir()
    (root / "outputs" / "BATCH_A").mkdir()
    (root / "outputs" / "BATCH_A" / "audit.json").write_text('{"batch_id":"BATCH_A"}',
                                                             encoding="utf-8")
    (root / "polish_descriptions").mkdir()
    return root


# ── provenance ────────────────────────────────────────────────────────────────

def test_harness_exists_at_durable_path():
    assert HARNESS_PATH.exists(), f"harness missing at {HARNESS_PATH}"


def test_v1_lineage_recorded(H):
    """The hardened harness must carry its v1 provenance, not silently drop it."""
    assert H.V1_SOURCE_SHA256 == V1_SOURCE_SHA256
    assert H.HARNESS_VERSION >= 2
    assert H.BASELINE == "c0416e88d5934775ea5dd90ef92463d6a3aab0e2"


# ── hashing ───────────────────────────────────────────────────────────────────

def test_hash_tree_covers_whole_tree_recursively(H, fixture_storage: Path):
    """Whole-tree hashing, not a curated list: nested evidence must be covered."""
    h = H.hash_tree(fixture_storage)
    assert "version.json" in h
    assert "packing.db" in h
    assert "master_audit.sqlite" in h, "HAZARD A: master_audit must be hash-protected"
    assert str(Path("outputs") / "BATCH_A" / "audit.json") in h


def test_hash_tree_excludes_wal_sidecars(H, fixture_storage: Path):
    con = sqlite3.connect(fixture_storage / "packing.db")
    con.execute("INSERT INTO t (v) VALUES ('wal')")
    con.commit()
    con.close()
    h = H.hash_tree(fixture_storage)
    assert not [k for k in h if k.endswith(("-wal", "-shm"))]


def test_hash_tree_detects_mutation(H, fixture_storage: Path):
    pre = H.hash_tree(fixture_storage)
    (fixture_storage / "version.json").write_text('{"v": 2}', encoding="utf-8")
    post = H.hash_tree(fixture_storage)
    d = H.diff_hashes(pre, post)
    assert d["changed"] == ["version.json"]


def test_diff_hashes_detects_added_and_removed(H, fixture_storage: Path):
    pre = H.hash_tree(fixture_storage)
    (fixture_storage / "new.json").write_text("{}", encoding="utf-8")
    (fixture_storage / "version.json").unlink()
    d = H.diff_hashes(pre, H.hash_tree(fixture_storage))
    assert "new.json" in d["added"]
    assert "version.json" in d["removed"]


# ── snapshot ──────────────────────────────────────────────────────────────────

def test_snapshot_mirrors_entire_storage_root(H, fixture_storage: Path, tmp_path: Path):
    """HAZARD B: every storage child must exist in the snapshot, not just DBs."""
    snap = tmp_path / "snap"
    st = H.snapshot_storage_root(fixture_storage, snap, lambda *_: None)
    assert st["sqlite_backup"] >= 3, "SQLite files must use the online-backup API"
    for child in ("packing.db", "documents.db", "master_audit.sqlite",
                  "version.json", "outputs", "polish_descriptions"):
        assert (snap / child).exists(), f"{child} missing from snapshot"
    assert (snap / "outputs" / "BATCH_A" / "audit.json").exists(), \
        "session/output evidence must be copied into the snapshot"


def test_snapshot_does_not_mutate_source(H, fixture_storage: Path, tmp_path: Path):
    pre = H.hash_tree(fixture_storage)
    H.snapshot_storage_root(fixture_storage, tmp_path / "snap", lambda *_: None)
    assert H.diff_hashes(pre, H.hash_tree(fixture_storage)) == {
        "changed": [], "removed": [], "added": []}


def test_snapshot_is_independent_of_source(H, fixture_storage: Path, tmp_path: Path):
    """Writing to the snapshot must never propagate back to live."""
    snap = tmp_path / "snap"
    H.snapshot_storage_root(fixture_storage, snap, lambda *_: None)
    pre_live = H.hash_tree(fixture_storage)
    con = sqlite3.connect(snap / "packing.db")
    con.execute("INSERT INTO t (v) VALUES ('snapshot-only')")
    con.commit(); con.close()
    assert H.diff_hashes(pre_live, H.hash_tree(fixture_storage))["changed"] == []
    con = sqlite3.connect(f"file:{(snap / 'packing.db').as_posix()}?mode=ro", uri=True)
    assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    con.close()
    con = sqlite3.connect(f"file:{(fixture_storage / 'packing.db').as_posix()}?mode=ro",
                          uri=True)
    assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1, \
        "live DB must still hold only the seed row"
    con.close()


def test_snapshot_creates_expected_app_directories(H, fixture_storage: Path, tmp_path: Path):
    snap = tmp_path / "snap"
    H.snapshot_storage_root(fixture_storage, snap, lambda *_: None)
    for d in ("outputs", "sessions", "working", "archived", "sad_ready"):
        assert (snap / d).is_dir()


# ── network kill-switch ───────────────────────────────────────────────────────

def test_network_killswitch_blocks_external_and_names_caller(H):
    import socket
    orig_connect, orig_connect_ex = socket.socket.connect, socket.socket.connect_ex
    try:
        state = H.install_network_killswitch(lambda *_: None)
        assert state["armed"] is True
        s = socket.socket(); s.settimeout(1)
        with pytest.raises(H.NetworkBlocked) as exc:
            s.connect(("203.0.113.1", 80))          # TEST-NET-3, never routable
        msg = str(exc.value)
        assert "OUTBOUND NETWORK BLOCKED" in msg
        assert "caller" in msg, "the blocked caller must be identified"
        assert state["blocked"] >= 1
    finally:
        socket.socket.connect, socket.socket.connect_ex = orig_connect, orig_connect_ex


def test_network_killswitch_records_attempts(H):
    import socket
    orig_connect, orig_connect_ex = socket.socket.connect, socket.socket.connect_ex
    try:
        state = H.install_network_killswitch(lambda *_: None)
        s = socket.socket(); s.settimeout(1)
        with pytest.raises(H.NetworkBlocked):
            s.connect(("198.51.100.7", 443))        # TEST-NET-2
        assert state["attempts"], "every attempt must be recorded"
        assert "198.51.100.7" in state["attempts"][-1]["addr"]
    finally:
        socket.socket.connect, socket.socket.connect_ex = orig_connect, orig_connect_ex


# ── import-order guard ────────────────────────────────────────────────────────

def test_import_order_guard_flags_pre_imported_app(H, monkeypatch):
    """If app.* is already imported, its storage constants bound to LIVE paths."""
    import types
    monkeypatch.setitem(sys.modules, "app.services.fake_probe",
                        types.ModuleType("app.services.fake_probe"))
    res = H.assert_import_order_guard(lambda *_: None)
    assert res["pass"] is False
    assert "app.services.fake_probe" in res["pre_imported"]


# ── CLI safety ────────────────────────────────────────────────────────────────

def test_no_phase_never_runs_implicitly(H, fixture_storage: Path, tmp_path: Path,
                                        monkeypatch):
    """A bare invocation must refuse, never silently execute a phase."""
    monkeypatch.setattr(sys, "argv",
                        ["ej_replay_harness.py", "--storage", str(fixture_storage),
                         "--out", str(tmp_path / "out")])
    with pytest.raises(SystemExit) as exc:
        H.main()
    assert exc.value.code == 2


def test_refuses_snapshot_equal_to_live(H, fixture_storage: Path, monkeypatch):
    """out/snap resolving onto live storage must be refused, not attempted."""
    monkeypatch.setattr(sys, "argv",
                        ["ej_replay_harness.py", "--storage", str(fixture_storage),
                         "--out", str(fixture_storage.parent), "--phase", "1"])
    # out/snap == live only if live is named "snap"; emulate by pointing --storage
    # at a dir whose parent/snap is itself.
    snapdir = fixture_storage.parent / "snap"
    snapdir.mkdir(exist_ok=True)
    monkeypatch.setattr(sys, "argv",
                        ["ej_replay_harness.py", "--storage", str(snapdir),
                         "--out", str(fixture_storage.parent), "--phase", "1"])
    assert H.main() == 2


def test_missing_storage_is_precondition_failure(H, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "argv",
                        ["ej_replay_harness.py", "--storage", str(tmp_path / "nope"),
                         "--out", str(tmp_path / "out"), "--phase", "1"])
    assert H.main() == 2


# ── phase helpers are read-only ───────────────────────────────────────────────

def test_phase1_discover_on_empty_snapshot_is_safe(H, fixture_storage: Path,
                                                   tmp_path: Path):
    snap = tmp_path / "snap"
    H.snapshot_storage_root(fixture_storage, snap, lambda *_: None)
    pre = H.hash_tree(snap)
    corpus = H.phase1_discover(snap)          # tables absent -> graceful empty
    assert corpus == {}
    assert H.diff_hashes(pre, H.hash_tree(snap))["changed"] == [], \
        "discovery must not write, even to the snapshot"


def test_query_helpers_tolerate_missing_tables(H, fixture_storage: Path):
    assert H.q(fixture_storage / "packing.db", "SELECT * FROM does_not_exist") == []
    assert H.scalar(fixture_storage / "packing.db", "SELECT COUNT(*) FROM nope") == 0


# ── Phase 1b: Product Fiscal Convergence (local evidence only) ────────────────

def _ev(mirror=None, mapping=None, cache=None, available=True):
    return {"mirror": mirror or {}, "mapping": mapping or {},
            "cache": cache or {}, "available": available}


def test_fiscal_mapping_exists_via_mirror_first(H):
    """Mirror is the primary fiscal read (matches _c1f_mirror_good_id)."""
    ev = _ev(mirror={"EJL/1": {"wfirma_id": "347088", "deleted": 0}})
    r = H.classify_fiscal_state("EJL/1", ev)
    assert r["fiscal_state"] == "WFIRMA_MAPPING_EXISTS"
    assert r["wfirma_id"] == "347088"


def test_fiscal_mapping_exists_via_cache_fallback(H):
    ev = _ev(cache={"EJL/2": {"wfirma_product_id": "999", "sync_status": "matched"}})
    assert H.classify_fiscal_state("EJL/2", ev)["fiscal_state"] == "WFIRMA_MAPPING_EXISTS"


def test_resolved_product_without_wfirma_id_is_registration_required(H):
    """The core D-6 distinction: identity resolved, fiscal registration absent.
    This must NOT be reported as a product-mapping problem."""
    r = H.classify_fiscal_state("EJL/26-27/549-1", _ev())
    assert r["identity"] == "PRODUCT_IDENTITY_RESOLVED"
    assert r["fiscal_state"] == "WFIRMA_REGISTRATION_REQUIRED"
    assert r["wfirma_id"] == ""


def test_pending_adoption_is_distinct_from_registration_required(H):
    """wFirma already holds the good — operator must choose adopt vs create.
    Never a silent duplicate create."""
    ev = _ev(mapping={"EJL/3": {"wfirma_product_id": "", "sync_status": "pending_adoption"}})
    assert H.classify_fiscal_state("EJL/3", ev)["fiscal_state"] == "WFIRMA_PENDING_ADOPTION"


def test_conflicting_ids_across_sources_is_conflict(H):
    ev = _ev(mirror={"EJL/4": {"wfirma_id": "111", "deleted": 0}},
             mapping={"EJL/4": {"wfirma_product_id": "222", "sync_status": "matched"}})
    r = H.classify_fiscal_state("EJL/4", ev)
    assert r["fiscal_state"] == "WFIRMA_MAPPING_CONFLICT"
    assert r["sources"]["mirror"] == "111" and r["sources"]["mapping"] == "222"


def test_deleted_mirror_row_does_not_count_as_mapped(H):
    ev = _ev(mirror={"EJL/5": {"wfirma_id": "555", "deleted": 1}})
    assert H.classify_fiscal_state("EJL/5", ev)["fiscal_state"] == "WFIRMA_REGISTRATION_REQUIRED"


def test_unreadable_evidence_is_reported_not_guessed(H):
    r = H.classify_fiscal_state("EJL/6", _ev(available=False))
    assert r["fiscal_state"] == "WFIRMA_LOCAL_EVIDENCE_UNAVAILABLE"


def test_fiscal_census_makes_no_network_call(H, fixture_storage: Path, tmp_path: Path):
    """Phase 1b must classify from local evidence only — never call wFirma."""
    import socket
    snap = tmp_path / "snap"
    H.snapshot_storage_root(fixture_storage, snap, lambda *_: None)
    orig_connect, orig_connect_ex = socket.socket.connect, socket.socket.connect_ex
    try:
        state = H.install_network_killswitch(lambda *_: None)
        res = H.phase1_fiscal_convergence(snap)      # would raise if it dialled out
        assert res["products_examined"] == 0         # fixture has no packing_lines
        assert state["blocked"] == 0, "fiscal census must not attempt any connection"
    finally:
        socket.socket.connect, socket.socket.connect_ex = orig_connect, orig_connect_ex


def test_fiscal_census_is_read_only(H, fixture_storage: Path, tmp_path: Path):
    snap = tmp_path / "snap"
    H.snapshot_storage_root(fixture_storage, snap, lambda *_: None)
    pre_live, pre_snap = H.hash_tree(fixture_storage), H.hash_tree(snap)
    H.phase1_fiscal_convergence(snap)
    H.phase1_d6_impact(snap)
    assert H.diff_hashes(pre_live, H.hash_tree(fixture_storage))["changed"] == []
    assert H.diff_hashes(pre_snap, H.hash_tree(snap))["changed"] == []


def test_d6_impact_tolerates_absent_drafts_table(H, fixture_storage: Path, tmp_path: Path):
    snap = tmp_path / "snap"
    H.snapshot_storage_root(fixture_storage, snap, lambda *_: None)
    d6 = H.phase1_d6_impact(snap)
    assert d6["drafts_examined"] == 0
    assert d6["blocked_solely_by_missing_wfirma_id"] == 0
    assert "not_locally_determinable_note" in d6, \
        "the honesty limit must always be reported, never implied absent"


def test_lineage_records_v1_and_v2(H):
    """v3 must carry lineage, not re-claim an older hash for new content."""
    assert H.V1_SOURCE_SHA256 == V1_SOURCE_SHA256
    assert H.V2_HARDENED_SHA256 == \
        "ec4e53925d9b2ca1c04a9a2a26f2c0ec26e67cefef1ca2cb68df005689ff5d71"
    assert H.HARNESS_VERSION >= 3
