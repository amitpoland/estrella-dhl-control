"""
Slice 1 browser acceptance — 5 scenarios (B worktree only).
Reports-only. Product code not modified.
Uses DEVNULL for uvicorn child (avoids PIPE deadlock).
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
OUT = Path(r"C:\PZ-wt\rbac-s1\reports\inspection\ab-v2-mount\acceptance-b")
OUT.mkdir(parents=True, exist_ok=True)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_shell(page, timeout_ms=90000):
    page.wait_for_function(
        "() => typeof window.Sidebar === 'function' && document.getElementById('root') && document.getElementById('root').childElementCount > 0",
        timeout=timeout_ms,
    )
    # Prefer Slice-1 marker when present
    try:
        page.wait_for_selector("[data-testid=v2-shell-root]", timeout=15000)
    except Exception:
        pass


def login(page, base, email):
    page.goto(base + "/login", wait_until="domcontentloaded")
    page.fill("#email", email)
    page.fill("#password", "TestPass123!")
    with page.expect_navigation(timeout=30000):
        page.click("button[type=submit]")


def main() -> int:
    storage = Path(tempfile.mkdtemp(prefix="s1_accept_"))
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
create_user(full_name="Acc Logistics", company_name="EJ", email="acc.logistics@example.com", password="TestPass123!", role="logistics", is_approved=True, email_verified=True)
create_user(full_name="Acc CRM", company_name="EJ", email="acc.crm@example.com", password="TestPass123!", role="crm", is_approved=True, email_verified=True)
create_user(full_name="Acc Viewer", company_name="EJ", email="acc.viewer@example.com", password="TestPass123!", role="viewer", is_approved=True, email_verified=True)
import uvicorn
uvicorn.run("app.main:app", host="127.0.0.1", port={port}, log_level="warning")
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SERVICE)
    proc = subprocess.Popen(
        [sys.executable, str(boot)],
        cwd=str(SERVICE),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    report = {"base": base, "checks": [], "ok": False}
    try:
        for _ in range(90):
            if proc.poll() is not None:
                report["error"] = "server_exited"
                (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                return 2
            try:
                urllib.request.urlopen(base + "/login", timeout=1)
                break
            except Exception:
                time.sleep(0.25)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()

            # 1) Logistics landing
            login(page, base, "acc.logistics@example.com")
            wait_shell(page)
            c1 = "/v2/shipments" in page.url
            report["checks"].append({"name": "1_logistics_landing", "url": page.url, "pass": c1})
            page.screenshot(path=str(OUT / "01-logistics.png"))

            # 2) Denied nav absent for CRM (Accounting / Inventory / admin Settings)
            page.context.clear_cookies()
            login(page, base, "acc.crm@example.com")
            wait_shell(page)
            nav = page.locator("[data-testid=v2-sidebar-nav]").inner_text() if page.locator("[data-testid=v2-sidebar-nav]").count() else page.locator("nav").first.inner_text()
            c2 = ("Accounting" not in nav) and ("Inventory" not in nav) and ("Inbox" in nav) and ("/v2/inbox" in page.url)
            report["checks"].append({"name": "2_crm_nav_hides_denied", "url": page.url, "pass": c2, "nav_sample": nav[:500]})
            page.screenshot(path=str(OUT / "02-crm-nav.png"))

            # 3) Direct denied URL cannot render protected page
            page.goto(base + "/v2/accounting", wait_until="domcontentloaded")
            wait_shell(page)
            page.wait_for_timeout(1500)
            url3 = page.url
            # Should leave accounting
            c3 = "/v2/accounting" not in url3 and "/v2/inbox" in url3
            report["checks"].append({"name": "3_crm_direct_url_denied", "url": url3, "pass": c3})
            page.screenshot(path=str(OUT / "03-crm-denied.png"))

            # 4) Refresh/deep-link same authorization
            page.goto(base + "/v2/inbox", wait_until="domcontentloaded")
            wait_shell(page)
            page.reload(wait_until="domcontentloaded")
            wait_shell(page)
            nav4 = page.locator("[data-testid=v2-sidebar-nav]").inner_text() if page.locator("[data-testid=v2-sidebar-nav]").count() else ""
            c4 = "/v2/inbox" in page.url and "Accounting" not in nav4
            report["checks"].append({"name": "4_crm_refresh_persistence", "url": page.url, "pass": c4})
            page.screenshot(path=str(OUT / "04-crm-refresh.png"))

            # 5) Malformed /auth/me fails closed — logout + /login; never keep protected URL
            page.route("**/auth/me", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"id": "x", "email": "x@y.z"}),
            ))
            page.goto(base + "/v2/accounting", wait_until="domcontentloaded")
            snap = {"url": page.url}
            try:
                page.wait_for_url(lambda u: "/login" in u and "/v2/" not in u, timeout=20000)
                snap = {"url": page.url, "landed_login": True}
                c5 = "/login" in page.url and "/v2/" not in page.url
            except Exception as ex:
                try:
                    snap = page.evaluate(
                        """() => {
                          const nav = document.querySelector('[data-testid=v2-sidebar-nav]');
                          return {
                            url: location.href,
                            navText: nav ? nav.innerText.slice(0, 300) : '',
                            hasAccountingNav: !!(nav && nav.innerText.indexOf('Accounting') >= 0),
                            readyState: document.readyState,
                          };
                        }"""
                    )
                except Exception as ex2:
                    snap = {"url": getattr(page, "url", ""), "eval_error": str(ex2), "wait_error": str(ex)}
                c5 = False
            report["checks"].append({"name": "5_malformed_auth_me_fail_closed", "pass": c5, "snap": snap})
            try:
                page.screenshot(path=str(OUT / "05-malformed.png"))
            except Exception:
                pass
            try:
                page.unroute("**/auth/me")
            except Exception:
                pass

            browser.close()

        report["ok"] = all(c.get("pass") for c in report["checks"])
        (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    except Exception as fatal:
        report["fatal"] = str(fatal)
        (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
