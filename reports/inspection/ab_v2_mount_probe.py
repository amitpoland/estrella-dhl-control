"""
A/B V2 shell-mount probe — NO product edits.

Usage:
  python ab_v2_mount_probe.py --label A --service-root C:\\PZ-wt\\rbac-s1-base-probe\\service --out ...
  python ab_v2_mount_probe.py --label B --service-root C:\\PZ-wt\\rbac-s1\\service --out ...

Shared mount signal (works on baseline AND Slice 1):
  #root.childElementCount > 0 after login → /v2/shipments
Slice-1-only markers are recorded but not required for A.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def redact_me(body: dict) -> dict:
    if not isinstance(body, dict):
        return {"_type": type(body).__name__}
    keep = {
        "id": bool(body.get("id")),
        "email": ("***" if body.get("email") else None),
        "role": body.get("role"),
        "default_surface": body.get("default_surface"),
        "default_page": body.get("default_page"),
        "permissions_count": len(body.get("permissions") or []) if isinstance(body.get("permissions"), list) else None,
        "allowed_pages": body.get("allowed_pages") if isinstance(body.get("allowed_pages"), list) else None,
        "keys": sorted(body.keys()),
    }
    return keep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--service-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mount-timeout-ms", type=int, default=90000)
    args = ap.parse_args()

    service = Path(args.service_root).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    label = args.label

    # Resolve git SHA of the tree that owns service/
    tree = service.parent
    sha = subprocess.check_output(["git", "-C", str(tree), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(tree), "status", "--porcelain"], text=True)

    storage = Path(tempfile.mkdtemp(prefix=f"ab_mount_{label}_"))
    port = free_port()
    boot = storage / "boot.py"
    boot.write_text(
        f"""
import sys
sys.path.insert(0, r"{service}")
from pathlib import Path
storage = Path(r"{storage}")
from app.core import config
config.settings.storage_root = storage
config.settings.auth_db_path = str(storage / "users.db")
config.settings.environment = "dev"
from app.auth.database import init_db
init_db(storage / "users.db")
from app.auth.service import create_user
create_user(
    full_name="Probe Logistics", company_name="EJ",
    email="probe.logistics@example.com", password="TestPass123!",
    role="logistics", is_approved=True, email_verified=True,
)
import uvicorn
uvicorn.run("app.main:app", host="127.0.0.1", port={port}, log_level="warning")
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(service)
    env["ENVIRONMENT"] = "dev"
    # PIPE deadlocks when uvicorn fills the buffer; a log file keeps the probe
    # alive AND keeps the traceback when the server dies during boot.
    boot_log = storage / "boot.log"
    proc = subprocess.Popen(
        [sys.executable, str(boot)],
        cwd=str(service),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=open(boot_log, "wb"),
    )
    base = f"http://127.0.0.1:{port}"
    report = {
        "label": label,
        "service_root": str(service),
        "tree": str(tree),
        "sha": sha,
        "dirty_porcelain_lines": len([ln for ln in dirty.splitlines() if ln.strip()]),
        "base_url": base,
        "has_authority_consumer_file": (service / "app/static/v2/authority-consumer.js").is_file(),
        "mount_timeout_ms": args.mount_timeout_ms,
        "ok_mount": False,
        "classification_hint": None,
    }

    try:
        for _ in range(90):
            if proc.poll() is not None:
                report["server_exit"] = boot_log.read_text(encoding="utf-8", errors="replace")[-3000:]
                (out_dir / f"{label}-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(json.dumps(report, indent=2))
                return 2
            try:
                urllib.request.urlopen(base + "/login", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        else:
            report["error"] = "server_not_ready"
            (out_dir / f"{label}-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            return 2

        console = []
        pageerrors = []
        failed_reqs = []
        v2_assets = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()

            def on_console(msg):
                console.append({"type": msg.type, "text": msg.text[:500]})

            def on_pageerror(err):
                pageerrors.append(str(err)[:1000])

            def on_request_failed(req):
                failed_reqs.append({"url": req.url, "failure": (req.failure or "")[:300]})

            def on_response(resp):
                u = resp.url
                if "/v2/" in u and any(u.endswith(ext) or f".{ext}?" in u for ext in ("js", "jsx", "css", "html")):
                    if len(v2_assets) < 80:
                        v2_assets.append({"url": u.replace(base, ""), "status": resp.status})

            page.on("console", on_console)
            page.on("pageerror", on_pageerror)
            page.on("requestfailed", on_request_failed)
            page.on("response", on_response)

            page.goto(base + "/login", wait_until="domcontentloaded", timeout=30000)
            page.fill("#email", "probe.logistics@example.com")
            page.fill("#password", "TestPass123!")
            with page.expect_navigation(timeout=30000):
                page.click("button[type=submit]")
            report["post_login_url"] = page.url

            # Prefer shipments if redirected there; else go explicitly
            if "/v2/" not in page.url:
                page.goto(base + "/v2/shipments", wait_until="domcontentloaded", timeout=30000)
            report["v2_url"] = page.url

            # Shared mount wait: #root gets children when App renders
            mounted = False
            deadline = time.time() + (args.mount_timeout_ms / 1000.0)
            last_snap = {}
            while time.time() < deadline:
                last_snap = page.evaluate(
                    """() => {
                      const root = document.getElementById('root');
                      return {
                        readyState: document.readyState,
                        hasReact: typeof React !== 'undefined',
                        hasReactDOM: typeof ReactDOM !== 'undefined',
                        hasBabel: typeof Babel !== 'undefined',
                        hasSidebar: typeof window.Sidebar === 'function',
                        hasAuthorityConsumer: typeof window.AuthorityConsumer === 'object' && window.AuthorityConsumer !== null,
                        rootChildren: root ? root.childElementCount : -1,
                        rootText: root ? (root.innerText || '').slice(0, 200) : null,
                        hasShellTestId: !!document.querySelector('[data-testid=v2-shell-root]'),
                        hasLoadingTestId: !!document.querySelector('[data-testid=v2-authority-loading]'),
                      };
                    }"""
                )
                if last_snap.get("rootChildren", 0) > 0:
                    mounted = True
                    break
                page.wait_for_timeout(500)

            report["mount_snapshot"] = last_snap
            report["ok_mount"] = mounted

            # /auth/me (redacted)
            try:
                me = page.evaluate(
                    """async () => {
                      const r = await fetch('/auth/me', {credentials:'include'});
                      let body = null;
                      try { body = await r.json(); } catch (e) { body = {parse_error: String(e)}; }
                      return {status: r.status, body};
                    }"""
                )
                report["auth_me"] = {"status": me.get("status"), "body": redact_me(me.get("body") or {})}
            except Exception as e:
                report["auth_me"] = {"error": str(e)}

            report["console"] = console[-40:]
            report["pageerrors"] = pageerrors[-20:]
            report["failed_requests"] = failed_reqs[:40]
            report["v2_asset_statuses"] = v2_assets
            report["failed_v2_assets"] = [a for a in v2_assets if a["status"] >= 400]

            page.screenshot(path=str(out_dir / f"{label}-after-wait.png"), full_page=True)
            (out_dir / f"{label}-root.html").write_text(
                page.evaluate("() => document.getElementById('root') ? document.getElementById('root').outerHTML.slice(0, 5000) : ''"),
                encoding="utf-8",
            )
            browser.close()

        if mounted:
            report["classification_hint"] = "MOUNT_OK"
        else:
            report["classification_hint"] = "MOUNT_TIMEOUT"

        (out_dir / f"{label}-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({k: report[k] for k in (
            "label", "sha", "dirty_porcelain_lines", "has_authority_consumer_file",
            "post_login_url", "v2_url", "ok_mount", "mount_snapshot", "auth_me",
            "classification_hint", "pageerrors",
        ) if k in report}, indent=2))
        return 0 if mounted else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
