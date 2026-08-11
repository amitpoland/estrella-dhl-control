"""
Fault injection: authority-consumer.js blocked for a logged-in CRM user
requesting the denied page /v2/accounting.

Protected content must NEVER render — not even transiently before the
fail-closed redirect. So we sample continuously from navigation start
rather than snapshotting once at the end.

Reports-only. No product edits.
"""
from __future__ import annotations

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

SERVICE = Path(r"C:\PZ-wt\rbac-s1\service")
OUT = Path(__file__).resolve().parent

# Substrings that only appear once the Accounting/Ledger surface has rendered.
PROTECTED_MARKERS = ("ledger", "management analysis", "supplier ledger",
                     "accounts receivable", "outstanding")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main() -> int:
    storage = Path(tempfile.mkdtemp(prefix="ac_missing_"))
    port = free_port()
    boot = storage / "boot.py"
    boot.write_text(
        f"""
import sys
sys.path.insert(0, r"{SERVICE}")
from pathlib import Path
storage = Path(r"{storage}")
from app.core import config
config.settings.storage_root = storage
config.settings.auth_db_path = str(storage / "users.db")
config.settings.environment = "dev"
from app.auth.database import init_db
init_db(storage / "users.db")
from app.auth.service import create_user
create_user(full_name="AC CRM", company_name="EJ", email="ac.crm@example.com",
            password="TestPass123!", role="crm", is_approved=True, email_verified=True)
import uvicorn
uvicorn.run("app.main:app", host="127.0.0.1", port={port}, log_level="warning")
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SERVICE)
    proc = subprocess.Popen(
        [sys.executable, str(boot)], cwd=str(SERVICE), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    report = {"base": base, "samples": [], "protected_ever_rendered": False}
    try:
        for _ in range(90):
            try:
                urllib.request.urlopen(base + "/login", timeout=1)
                break
            except Exception:
                time.sleep(0.25)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()

            # Log in normally (consumer available) so we hold a valid session.
            page.goto(base + "/login", wait_until="domcontentloaded")
            page.fill("#email", "ac.crm@example.com")
            page.fill("#password", "TestPass123!")
            with page.expect_navigation(timeout=30000):
                page.click("button[type=submit]")

            # Now simulate authority-consumer.js failing to load.
            page.route("**/authority-consumer.js", lambda r: r.abort())
            page.goto(base + "/v2/accounting", wait_until="domcontentloaded")

            # Sample continuously through mount, render and any redirect.
            worst = None
            deadline = time.time() + 60
            landed_login = False
            while time.time() < deadline:
                try:
                    s = page.evaluate(
                        """(markers) => {
                          const nav = document.querySelector('[data-testid=v2-sidebar-nav]');
                          const body = (document.body && document.body.innerText || '').toLowerCase();
                          return {
                            url: location.href,
                            hasAC: typeof window.AuthorityConsumer === 'object'
                                   && window.AuthorityConsumer !== null,
                            navShowsAccounting: !!(nav && nav.innerText.indexOf('Accounting') >= 0),
                            hits: markers.filter(m => body.indexOf(m) >= 0),
                          };
                        }""",
                        list(PROTECTED_MARKERS),
                    )
                except Exception:
                    time.sleep(0.1)
                    continue
                leaked = bool(s["hits"]) or s["navShowsAccounting"]
                if leaked and worst is None:
                    worst = s
                if len(report["samples"]) < 6:
                    report["samples"].append(s)
                if "/login" in s["url"] and "/v2/" not in s["url"]:
                    landed_login = True
                    report["final"] = s
                    break
                time.sleep(0.1)

            if "final" not in report:
                report["final"] = s
            report["landed_login"] = landed_login
            report["worst_leak"] = worst
            report["protected_ever_rendered"] = worst is not None
            page.screenshot(path=str(OUT / "ac-missing.png"), full_page=True)
            browser.close()

        report["fails_open"] = bool(
            report["protected_ever_rendered"]
            or "/v2/accounting" in report["final"]["url"]
        )
        print(json.dumps(report, indent=2)[:3000])
        return 1 if report["fails_open"] else 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
