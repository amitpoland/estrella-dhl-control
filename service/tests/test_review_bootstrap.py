"""
GATE-6 review-bootstrap safety + seed tests.

Proves the review launcher fails closed and the seed harness produces a
deterministic, isolated, live-write-free two-client transport scenario.

These run in normal pytest and stay green regardless of tree: #940-only
assertions (carrier per-client scoping) gate on the seed's reported
``carrier_client_scoped`` capability. To exercise the full #940 scenario,
point the seed at the served tree:

    REVIEW_APP_DIR=C:/PZ-wt/review-940-tree/service pytest tests/test_review_bootstrap.py -v
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_SERVICE = Path(__file__).resolve().parents[1]          # …/service
_SCRIPTS = _SERVICE / "scripts"
_LAUNCH = _SCRIPTS / "review_launch.py"
_SEED = _SCRIPTS / "review_seed.py"
# App tree to seed against: an override (the served #940 tree) or this repo's own.
_APP_DIR = Path(os.environ.get("REVIEW_APP_DIR", str(_SERVICE)))


def _run(args, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    e["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          env=e, timeout=180)


# ── Launcher fail-closed (safety core) ────────────────────────────────────────

def test_launcher_refuses_live_storage_root(tmp_path):
    """A storage root that overlaps a live/production root is refused."""
    live_root = _SERVICE / "app" / "storage"
    r = _run([str(_LAUNCH), "--app-dir", str(_APP_DIR), "--storage-root",
              str(live_root), "--commit", "test", "--print-config"])
    assert r.returncode == 2, r.stderr
    assert "REFUSED" in r.stderr and "overlaps a live" in r.stderr


def test_launcher_refuses_production_root_unconditionally(tmp_path):
    """The hardcoded production tree C:\\PZ is refused even when STORAGE_ROOT is
    NOT set in the shell (NSSM sets it on the service process, not a hand shell)."""
    env = {k: "" for k in ("STORAGE_ROOT",)}  # ensure host STORAGE_ROOT is absent
    r = _run([str(_LAUNCH), "--app-dir", str(_APP_DIR), "--storage-root",
              r"C:\PZ\storage", "--commit", "x", "--print-config"], env=env)
    assert r.returncode == 2 and "overlaps a live" in r.stderr


def test_launcher_refuses_case_variant_production_root(tmp_path):
    """Windows is case-insensitive: a lowercase production path must still refuse."""
    env = {"STORAGE_ROOT": ""}
    r = _run([str(_LAUNCH), "--app-dir", str(_APP_DIR), "--storage-root",
              r"c:\pz\storage", "--commit", "x", "--print-config"], env=env)
    assert r.returncode == 2 and "overlaps a live" in r.stderr


def test_launcher_refuses_bad_app_dir(tmp_path):
    r = _run([str(_LAUNCH), "--app-dir", str(tmp_path / "nope"), "--storage-root",
              str(tmp_path / "rev"), "--commit", "test", "--print-config"])
    assert r.returncode == 2
    assert "does not contain app/main.py" in r.stderr


def test_launcher_strips_host_live_credentials(tmp_path):
    """Even when the HOST env carries DHL/wFirma creds + write flags, the review
    config is neutralised: no live creds, no write flags, carrier shadow."""
    poisoned = {
        "DHL_EXPRESS_API_KEY": "LIVE-XXX", "DHL_EXPRESS_API_SECRET": "LIVE-YYY",
        "DHL_TRACKING_API_KEY": "LIVE-DT", "WFIRMA_ACCESS_KEY": "LIVE-WF",
        "FEDEX_CLIENT_ID": "FX", "FEDEX_CLIENT_SECRET": "FXS",
        "SMTP_USER": "u@x", "SMTP_PASSWORD": "p", "CLIQ_WEBHOOK_URL": "http://live",
        "WORKDRIVE_REFRESH_TOKEN": "wr", "ANTHROPIC_API_KEY": "sk-live",
        "AI_COWORK_API_KEY": "ck", "DHL_WEBHOOK_SECRET": "hs",
        "WFIRMA_CREATE_INVOICE_ALLOWED": "true", "WFIRMA_SYNC_CUSTOMERS_ALLOWED": "true",
        "CARRIER_API_STATUS": "live", "CARRIER_LIVE_ALLOWLIST": "SOME-BATCH",
    }
    r = _run([str(_LAUNCH), "--app-dir", str(_APP_DIR), "--storage-root",
              str(tmp_path / "rev"), "--commit", "13d442e9", "--print-config"],
             env=poisoned)
    assert r.returncode == 0, r.stderr
    cfg = json.loads(r.stdout.strip().splitlines()[-1])
    assert cfg["carrier_api_status"] == "shadow"
    assert cfg["carrier_live_allowlist_empty"] is True
    assert cfg["live_credentials_present"] is False
    assert cfg["write_flags_on"] == []


def test_launcher_writes_version_fingerprint(tmp_path):
    sr = tmp_path / "rev"
    r = _run([str(_LAUNCH), "--app-dir", str(_APP_DIR), "--storage-root", str(sr),
              "--commit", "13d442e9", "--print-config"])
    assert r.returncode == 0, r.stderr
    version = json.loads((sr / "version.json").read_text())
    assert version["commit"] == "13d442e9"
    assert version["channel"] == "gate6-review"


# ── Seed: determinism, data correctness, isolation ────────────────────────────

def _seed(tmp_path):
    sr = tmp_path / "review-storage"
    r = _run([str(_SEED), "--app-dir", str(_APP_DIR), "--storage-root", str(sr),
              "--commit", "13d442e9", "--reset-review-data"])
    assert r.returncode == 0, r.stderr + "\n" + r.stdout
    manifest = json.loads((sr / "review-manifest.json").read_text())
    return sr, manifest


def test_seed_is_deterministic(tmp_path):
    _, m1 = _seed(tmp_path)
    _, m2 = _seed(tmp_path)  # re-seed same root (reset each time)
    assert m1["scenario"] == m2["scenario"]
    a = m1["scenario"]["clients"]["alpha"]
    assert a["expected_awb"] == "AWB1000000001"
    assert a["expected_invoice_number"] == "FV 7/2026"
    assert m1["scenario"]["clients"]["beta"]["expected_invoice_number"] is None


def test_seed_live_write_disabled_in_manifest(tmp_path):
    _, m = _seed(tmp_path)
    lw = m["live_write_disabled"]
    assert lw["carrier_api_status"] == "shadow"
    assert lw["carrier_live_allowlist_empty"] is True
    assert lw["dhl_credentials_present"] is False
    assert lw["wfirma_credentials_present"] is False
    assert lw["write_flags_on"] == []


def test_seed_invoice_full_number_and_honest_null(tmp_path):
    sr, _ = _seed(tmp_path)
    con = sqlite3.connect(str(sr / "proforma_links.db"))
    links = con.execute("SELECT proforma_number, invoice_number, status "
                        "FROM proforma_invoice_links").fetchall()
    # Alpha: exactly one ISSUED link with a full human number.
    issued = [r for r in links if r[2] == "issued"]
    assert len(issued) == 1 and issued[0][1] == "FV 7/2026"
    # Beta: no issued invoice link ⇒ honest null (only Alpha's row exists).
    assert all(r[1] != "FV 8/2026" for r in links)


def test_seed_two_clients_never_share_carrier_state(tmp_path):
    sr, m = _seed(tmp_path)
    if not m["scenario"]["carrier_client_scoped"]:
        pytest.skip("served tree predates #940 carrier client_ref scoping")
    con = sqlite3.connect(str(sr / "carrier" / "carrier_shipments.db"))
    rows = con.execute("SELECT client_ref, tracking_ref FROM carrier_shipments "
                       "WHERE client_ref IS NOT NULL").fetchall()
    by_client = dict(rows)
    assert by_client["REV-A"] == "AWB1000000001"
    assert by_client["REV-B"] == "AWB2000000002"
    assert by_client["REV-A"] != by_client["REV-B"]  # no shared AWB


def test_seed_legacy_null_client_row_present(tmp_path):
    sr, m = _seed(tmp_path)
    if not m["scenario"]["carrier_client_scoped"]:
        pytest.skip("served tree predates #940 carrier client_ref column")
    con = sqlite3.connect(str(sr / "carrier" / "carrier_shipments.db"))
    legacy = con.execute("SELECT tracking_ref FROM carrier_shipments "
                        "WHERE client_ref IS NULL").fetchall()
    assert ("AWB0000000000",) in legacy


def test_seed_resolution_isolates_clients(tmp_path):
    """The canonical #940 resolver attributes each client_ref to its OWN row and
    refuses to leak the legacy NULL row into a multi-client batch."""
    sr, m = _seed(tmp_path)
    if not m["scenario"]["carrier_client_scoped"]:
        pytest.skip("served tree predates #940 carrier client_ref scoping")
    # Query the resolver via a subprocess that imports from the served tree.
    check = (
        "import json,sys;"
        "sys.path.insert(0, r'%s');"
        "from app.services.carrier.persistence.shipment_db import get_shipment_for_draft as g;"
        "db=r'%s';"
        "a=g(db,'REVIEW-GATE6-940','REV-A');"
        "b=g(db,'REVIEW-GATE6-940','REV-B');"
        "n=g(db,'REVIEW-GATE6-940',None,allow_single_client_fallback=False);"
        "print(json.dumps({'a':a and a['tracking_ref'],'b':b and b['tracking_ref'],"
        "'null':None if n is None else n['tracking_ref']}))"
        % (str(_APP_DIR), str(sr / "carrier" / "carrier_shipments.db"))
    )
    r = _run(["-c", check])
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["a"] == "AWB1000000001"
    assert out["b"] == "AWB2000000002"
    assert out["null"] is None  # multi-client batch ⇒ legacy row NOT attributed


def test_seed_refuses_production_root(tmp_path):
    """The seeder shares the launcher's isolation guard — it must refuse a
    production/non-prod-tree storage root before any write or delete."""
    r = _run([str(_SEED), "--app-dir", str(_APP_DIR), "--storage-root",
              r"C:\PZ\storage", "--commit", "13d442e9", "--reset-review-data"],
             env={"STORAGE_ROOT": ""})
    assert r.returncode == 2 and "overlaps a live" in r.stderr


def test_seed_requires_commit(tmp_path):
    """Seeding without --commit is refused (manifest traceability)."""
    r = _run([str(_SEED), "--app-dir", str(_APP_DIR),
              "--storage-root", str(tmp_path / "rev")])
    assert r.returncode == 2 and "--commit is required" in r.stderr


def test_reset_removes_only_review_storage(tmp_path):
    sr, _ = _seed(tmp_path)
    sentinel = tmp_path / "OUTSIDE.txt"
    sentinel.write_text("keep me")
    assert sr.exists()
    r = _run([str(_SEED), "--storage-root", str(sr), "--reset-review-data"])
    assert r.returncode == 0, r.stderr
    assert not sr.exists()          # review storage gone
    assert sentinel.read_text() == "keep me"   # nothing outside touched
