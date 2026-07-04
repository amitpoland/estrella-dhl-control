#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CP3 Capture Harness — Wave-3
============================
Side-by-side screenshots: wireframe (LEFT) vs live app (RIGHT), no labels.
Filenames carry the mapping.

Usage:
    python scripts/cp3_capture.py

Outputs:
    reports/wave3/cp3/pair-NN-<name>.png        — paired side-by-side
    reports/wave3/cp3/only-wireframe-<name>.png — wireframe-only
    reports/wave3/cp3/only-live-<name>.png      — live-only
    reports/wave3/cp3/INDEX.md                  — mapping table

Requirements: playwright, pillow
    playwright install chromium  (or system Chrome at CHROME_PATH below)
"""

import asyncio
import sys
import io
import re
import time
from pathlib import Path

# Windows asyncio fix for Python ≤ 3.10
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright, Page
from PIL import Image

# ── Config ─────────────────────────────────────────────────────────────────────
REPO_ROOT    = Path("C:/PZ-verify")
OUT_DIR      = REPO_ROOT / "reports/wave3/cp3"
WF_PATH      = REPO_ROOT / "docs/design/estrella-dashboard-wireframe.html"
LIVE_BASE    = "http://127.0.0.1:8201"
CHROME_PATH  = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
VIEWPORT     = {"width": 1440, "height": 900}
SETTLE_MS    = 1500   # extra settle after network-idle


def slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def wait_settle(page: Page, timeout: int = 8000):
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    page.wait_for_timeout(SETTLE_MS)


def screenshot_pil(page: Page) -> Image.Image:
    data = page.screenshot(type="png", full_page=False)
    return Image.open(io.BytesIO(data))


def compose_side_by_side(left: Image.Image, right: Image.Image) -> Image.Image:
    target_h = min(left.height, right.height)

    def resize_h(img, h):
        ratio = h / img.height
        return img.resize((int(img.width * ratio), h), Image.LANCZOS)

    l = resize_h(left, target_h)
    r = resize_h(right, target_h)
    out = Image.new("RGB", (l.width + r.width, target_h), (240, 240, 240))
    out.paste(l, (0, 0))
    out.paste(r, (l.width, 0))
    return out


def save_png(img: Image.Image, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path), "PNG", optimize=True)
    kb = path.stat().st_size // 1024
    print(f"    saved {path.name} ({kb}KB)")


# ── Wireframe capture ──────────────────────────────────────────────────────────

# Wireframe nav: button index → (canonical_name, sub_tab_indices_or_None)
# Discovered from probe: aside buttons by index, Setup expands to reveal sub-items.
# Inventory tabs (11): Overview, Temp Purchase, Temp Warehouse, Temp Sale,
#   Consignment, Final Stock, Sample Out, Sample Return,
#   Goods Return from Client, Return to Producer, Identity / Mapping
# Accounting tabs (10+): Overview, Proforma/PI, Invoice/INV, Credit Note/CN,
#   WZ Outbound, PZ Inbound, PW Internal in, RW Internal out, MM Transfer,
#   Client Balance, Client Ledger, Supplier Ledger, wFirma Sync

WF_PAGES = [
    # (button_index_before_setup_expand, canonical_name)
    (0, "dashboard"),
    (1, "inbox"),
    (2, "shipments"),
    (3, "proforma"),
    (4, "documents"),
    (5, "accounting"),    # has sub-tabs
    (6, "inventory"),     # has sub-tabs
    (7, "reports"),
    # Setup group (index 8 = toggle): after clicking, items appear at 9..17
    # handled separately
]

WF_SETUP_PAGES = [
    # (index_after_expand, canonical_name)
    (9,  "setup_settings"),
    (10, "setup_master"),
    (11, "setup_carriers"),
    (12, "setup_wfirma"),
    (13, "setup_api_status"),
    (14, "setup_diagnostics"),
    (15, "setup_automation"),
    (16, "setup_intelligence"),
    (17, "setup_coverage"),
]

# Tab button texts in wireframe inventory (after clicking Inventory nav)
WF_INV_TAB_TEXTS = [
    "Overview",
    "Temp Purchase",
    "Temp Warehouse",
    "Temp Sale",
    "Consignment",
    "Final Stock",
    "Sample Out",
    "Sample Return",
    "Goods Return from Client",
    "Return to Producer",
    "Identity / Mapping",
]

# Tab button texts in wireframe accounting (after clicking Accounting nav)
WF_ACC_TAB_TEXTS = [
    "Overview",
    "Proforma",
    "Invoice",
    "Credit Note",
    "WZ",
    "PZ",
    "PW",
    "RW",
    "MM",
    "Client Balance",
    "Client Ledger",
    "Supplier Ledger",
    "wFirma Sync",
]


def get_main_buttons(page: Page):
    """Return buttons NOT in the aside sidebar."""
    return page.evaluate("""() => {
        const aside = document.querySelector('aside');
        const allBtns = Array.from(document.querySelectorAll('button'));
        return allBtns
            .filter(b => !aside || !aside.contains(b))
            .map((b, i) => ({
                index: i,
                text: b.textContent.trim().replace(/[^\\x20-\\x7E\\u00C0-\\u024F]/g, '').trim()
            }));
    }""")


def find_tab_button(page: Page, text_prefix: str):
    """Find the first main-area button whose text starts with text_prefix."""
    try:
        btns = get_main_buttons(page)
        for b in btns:
            if b["text"].lower().startswith(text_prefix.lower().strip()):
                # Get the actual element
                idx = b["index"]
                aside = page.query_selector("aside")
                all_btns = page.query_selector_all("button")
                main_btns = [b for b in all_btns if not (aside and aside.query_selector(f"button:nth-of-type({all_btns.index(b)+1})"))]
                # Simpler: use evaluate to click by index
                return idx
    except Exception:
        pass
    return None


def click_main_button_by_text(page: Page, text_prefix: str) -> bool:
    """Click a main-area button whose text starts with text_prefix."""
    result = page.evaluate(f"""() => {{
        const aside = document.querySelector('aside');
        const allBtns = Array.from(document.querySelectorAll('button'));
        const mainBtns = allBtns.filter(b => !aside || !aside.contains(b));
        const prefix = {json_str(text_prefix)};
        const target = mainBtns.find(b => {{
            const t = b.textContent.trim().replace(/[^\\x20-\\x7E\\u00C0-\\u024F]/g, '').trim();
            return t.toLowerCase().startsWith(prefix.toLowerCase());
        }});
        if (target) {{ target.click(); return true; }}
        return false;
    }}""")
    return bool(result)


def json_str(s: str) -> str:
    """Return a JSON-safe string literal."""
    import json
    return json.dumps(s)


def capture_wireframe(browser) -> tuple:
    """Screenshot every wireframe screen. Returns (screens_dict, errors_dict)."""
    context = browser.new_context(viewport=VIEWPORT)
    page = context.new_page()
    screens = {}
    errors = {}

    print("\n=== WIREFRAME CAPTURE ===")
    wf_url = WF_PATH.as_uri()
    page.goto(wf_url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)

    aside_btns = page.query_selector_all("aside button")
    print(f"  Found {len(aside_btns)} sidebar buttons")

    def click_nav(idx: int) -> bool:
        try:
            btns = page.query_selector_all("aside button")
            if idx < len(btns):
                btns[idx].click()
                page.wait_for_timeout(700)
                return True
        except Exception as e:
            print(f"    click_nav({idx}) error: {e}")
        return False

    def capture_page(name: str):
        try:
            wait_settle(page, timeout=5000)
            img = screenshot_pil(page)
            screens[name] = img
            print(f"  captured WF: {name} ({img.width}x{img.height})")
        except Exception as e:
            errors[name] = str(e)
            print(f"  ERROR WF {name}: {e}")

    # ── Primary pages ──
    for btn_idx, name in WF_PAGES:
        if name in ("accounting", "inventory"):
            # Handle sub-tabs below
            pass
        click_nav(btn_idx)
        capture_page(name)

    # ── Inventory tabs ──
    print("  WF: Inventory sub-tabs")
    click_nav(6)  # Inventory
    page.wait_for_timeout(500)
    for tab_text in WF_INV_TAB_TEXTS:
        tab_key = "inventory_tab_" + slugify(tab_text)
        clicked = click_main_button_by_text(page, tab_text)
        if clicked:
            page.wait_for_timeout(600)
            capture_page(tab_key)
        else:
            print(f"    WARN: could not click tab '{tab_text}'")
            errors[tab_key] = f"tab button not found: {tab_text}"

    # ── Accounting tabs ──
    print("  WF: Accounting sub-tabs")
    click_nav(5)  # Accounting
    page.wait_for_timeout(500)
    for tab_text in WF_ACC_TAB_TEXTS:
        tab_key = "accounting_tab_" + slugify(tab_text)
        clicked = click_main_button_by_text(page, tab_text)
        if clicked:
            page.wait_for_timeout(600)
            capture_page(tab_key)
        else:
            print(f"    WARN: could not click tab '{tab_text}'")
            errors[tab_key] = f"tab button not found: {tab_text}"

    # ── Shipments → detail ──
    print("  WF: Shipment detail (click first card)")
    click_nav(2)  # Shipments
    page.wait_for_timeout(500)
    try:
        # Try clicking the first shipment card in the list
        card = page.query_selector("tbody tr, .shipment-row, [class*='card']")
        if card:
            card.click()
            page.wait_for_timeout(800)
            wait_settle(page, timeout=4000)
            img = screenshot_pil(page)
            screens["shipment_detail"] = img
            print(f"  captured WF: shipment_detail ({img.width}x{img.height})")
        else:
            # Just capture shipments page and treat as detail placeholder
            pass
    except Exception as e:
        print(f"  Shipment detail: {e}")

    # ── Setup sub-pages ──
    print("  WF: Setup sub-pages")
    # First click Setup to expand
    click_nav(8)
    page.wait_for_timeout(600)
    for btn_idx, name in WF_SETUP_PAGES:
        click_nav(btn_idx)
        capture_page(name)

    context.close()
    return screens, errors


# ── Live app capture ────────────────────────────────────────────────────────────

# Live app slugs and names
LIVE_PRIMARY = [
    ("dashboard",          "dashboard"),
    ("inbox",              "inbox"),
    ("shipments",          "shipments"),
    ("dhl",                "dhl_customs"),
    ("proforma",           "proforma_list"),
    ("proforma_search",    "proforma_search"),
    ("documents",          "documents"),
    ("reports",            "reports"),
    ("master",             "master_data"),
    ("wfirma_setup",       "wfirma_setup"),
    ("carriers",           "carriers"),
    ("api_status",         "api_status"),
    ("diagnostics",        "diagnostics"),
    ("admin",              "admin_settings"),
    ("automation",         "automation"),
    ("coverage",           "coverage_map"),
    ("shipping_ops",       "shipping_ops"),
    ("intelligence",       "intelligence_hub"),
]

# Tab selectors to try for inventory and accounting
LIVE_TAB_SELECTORS = [
    '[data-testid="inv-tab-strip"] button',
    '[data-testid*="tab-strip"] button',
    '[class*="tab-strip"] button',
    '[role="tablist"] button',
    '[role="tab"]',
]


def discover_tabs(page: Page):
    """Find tab buttons in live app."""
    for sel in LIVE_TAB_SELECTORS:
        try:
            tabs = page.query_selector_all(sel)
            if tabs and len(tabs) > 1:
                return tabs
        except Exception:
            pass
    # Broader: find any strip of 3+ buttons in main content area
    try:
        result = page.evaluate("""() => {
            // Find button groups that look like tab strips
            const allContainers = document.querySelectorAll('div, nav, ul');
            for (const c of allContainers) {
                const btns = Array.from(c.children).filter(el => el.tagName === 'BUTTON');
                if (btns.length >= 3) {
                    return btns.map(b => b.textContent.trim().substring(0, 40));
                }
            }
            return [];
        }""")
        if result and len(result) >= 3:
            # Find and return corresponding elements
            for sel in ["div > button + button + button", "nav > button"]:
                tabs = page.query_selector_all(sel)
                if tabs and len(tabs) >= 3:
                    return tabs
    except Exception:
        pass
    return []


def capture_live(browser) -> tuple:
    """
    Screenshot every live app screen.
    Load the SPA ONCE then navigate via pushState (sidebar pattern).
    The SPA has background polling that prevents networkidle from ever settling
    on subsequent goto calls, so we load once and use JS navigation after.
    Returns (screens_dict, errors_dict).
    """
    context = browser.new_context(viewport=VIEWPORT)
    page = context.new_page()
    screens = {}
    errors = {}

    print("\n=== LIVE APP CAPTURE ===")

    # ── Initial SPA load (one goto only) ──
    print("  Loading SPA (networkidle, up to 90s)...")
    try:
        page.goto(f"{LIVE_BASE}/v2/dashboard", wait_until="networkidle", timeout=90000)
    except Exception:
        pass  # background polling prevents networkidle; just wait fixed time
    page.wait_for_timeout(4000)
    print(f"  SPA title: {page.title()}")

    def spa_nav(slug: str):
        """Navigate in the loaded SPA via pushState + popstate dispatch."""
        page.evaluate(f"""() => {{
            history.pushState({{page: '{slug}'}}, '', '/v2/{slug}');
            window.dispatchEvent(new PopStateEvent('popstate', {{state: {{page: '{slug}'}}}}));
        }}""")
        page.wait_for_timeout(2000)

    def capture(name: str):
        try:
            img = screenshot_pil(page)
            screens[name] = img
            print(f"  captured LIVE: {name} ({img.width}x{img.height})")
        except Exception as e:
            errors[name] = str(e)
            print(f"  ERROR LIVE {name}: {e}")

    # placeholder for backward compat (not used with spa_nav)
    def nav(slug: str):
        spa_nav(slug)

    def capture(name: str):
        try:
            img = screenshot_pil(page)
            screens[name] = img
            print(f"  captured LIVE: {name} ({img.width}x{img.height})")
        except Exception as e:
            errors[name] = str(e)
            print(f"  ERROR LIVE {name}: {e}")

    # ── Primary pages ──
    # Dashboard is already loaded from the initial goto
    capture("dashboard")

    for slug, name in LIVE_PRIMARY:
        if name == "dashboard":
            continue  # already captured above
        print(f"  LIVE → {slug}")
        try:
            spa_nav(slug)
            capture(name)
        except Exception as e:
            errors[name] = str(e)
            print(f"  ERROR nav {slug}: {e}")

    # ── Proforma detail (empty/error state) ──
    print("  LIVE → proforma_detail (empty state)")
    try:
        spa_nav("proforma_detail")
        capture("proforma_detail")
    except Exception as e:
        errors["proforma_detail"] = str(e)

    # ── Shipments + detail ──
    print("  LIVE → shipments + detail attempt")
    try:
        spa_nav("shipments")
        page.wait_for_timeout(1000)
        # Try clicking first shipment row
        rows = page.query_selector_all("tbody tr, [data-testid='shipment-row'], .shipment-row")
        if rows:
            rows[0].click()
            page.wait_for_timeout(1500)
            capture("shipment_detail")
        else:
            # No rows — capture shipments as "detail" placeholder
            img = screenshot_pil(page)
            screens["shipment_detail"] = img
            print(f"  captured LIVE: shipment_detail (empty state, no rows)")
    except Exception as e:
        errors["shipment_detail"] = str(e)
        print(f"  ERROR shipment detail: {e}")

    # ── Inventory + sub-tabs ──
    print("  LIVE → inventory + sub-tabs")
    try:
        spa_nav("inventory")
        capture("inventory")
        tabs = discover_tabs(page)
        print(f"    Found {len(tabs)} inventory tabs")
        for i, tab_el in enumerate(tabs[:12]):
            try:
                tab_text = (tab_el.text_content() or f"tab{i}").strip()
                tab_key = f"inventory_tab_{i}"
                tab_el.scroll_into_view_if_needed()
                tab_el.click()
                page.wait_for_timeout(800)
                img = screenshot_pil(page)
                screens[tab_key] = img
                print(f"    captured LIVE: {tab_key} ({tab_text!r})")
            except Exception as e:
                print(f"    inventory tab {i} error: {e}")
    except Exception as e:
        errors["inventory"] = str(e)
        print(f"  ERROR inventory: {e}")

    # ── Accounting + sub-tabs ──
    # Use the specific acc-rail selector (NOT generic tab-strip discovery which
    # collides with the Setup subnav). The accounting hub renders left-rail buttons
    # with data-testid="acc-rail-<id>" (AccRailGroup in accounting-hub.jsx:135).
    ACC_RAIL_IDS = [
        "purchase", "proforma", "ledger", "sync", "master", "audit",
        # gated (W4) — still screenshotted to document current state
        "wz", "pz", "pw", "rw", "mm",
    ]
    # 'sync' and 'master' are group='navigate' — clicking them navigates AWAY
    # from accounting, destroying the rail DOM. Re-navigate to accounting before
    # each button so DOM is always fresh.
    print("  LIVE → accounting + sub-tabs")
    try:
        spa_nav("accounting")
        capture("accounting")
        for i, rail_id in enumerate(ACC_RAIL_IDS):
            try:
                # Always return to accounting before each click (handles navigate-group
                # buttons that leave the page)
                spa_nav("accounting")
                btn = page.query_selector(f'[data-testid="acc-rail-{rail_id}"]')
                if not btn:
                    print(f"    accounting rail {rail_id}: selector not found after re-nav, skipping")
                    continue
                tab_text = (btn.text_content() or rail_id).strip()
                tab_key = f"accounting_tab_{i}"
                btn.scroll_into_view_if_needed()
                btn.click()
                page.wait_for_timeout(1000)
                img = screenshot_pil(page)
                screens[tab_key] = img
                print(f"    captured LIVE: {tab_key} acc-rail-{rail_id} ({tab_text!r})")
            except Exception as e:
                print(f"    accounting tab acc-rail-{rail_id} error: {e}")
    except Exception as e:
        errors["accounting"] = str(e)
        print(f"  ERROR accounting: {e}")

    context.close()
    return screens, errors


# ── Pairing ────────────────────────────────────────────────────────────────────

# Static pair map: (wireframe_name, live_name)
STATIC_PAIRS = [
    ("dashboard",           "dashboard"),
    ("inbox",               "inbox"),
    ("shipments",           "shipments"),
    ("shipment_detail",     "shipment_detail"),
    ("proforma",            "proforma_list"),
    ("documents",           "documents"),
    ("accounting",          "accounting"),
    ("inventory",           "inventory"),
    ("reports",             "reports"),
    ("setup_settings",      "admin_settings"),
    ("setup_master",        "master_data"),
    ("setup_carriers",      "carriers"),
    ("setup_wfirma",        "wfirma_setup"),
    ("setup_api_status",    "api_status"),
    ("setup_diagnostics",   "diagnostics"),
    ("setup_automation",    "automation"),
    ("setup_intelligence",  "intelligence_hub"),
    ("setup_coverage",      "coverage_map"),
]

# Inventory tab pairing: wireframe tab names → live tab indices
WF_INV_TABS_ORDERED = [slugify(t) for t in WF_INV_TAB_TEXTS]   # 11 items

# Accounting tab pairing
WF_ACC_TABS_ORDERED = [slugify(t) for t in WF_ACC_TAB_TEXTS]   # 13 items


def build_pairs(wf_screens: dict, live_screens: dict):
    pairs = []
    wf_paired = set()
    live_paired = set()

    def add_pair(wf_name, live_name, display_name):
        nonlocal pairs
        wf_img = wf_screens.get(wf_name)
        live_img = live_screens.get(live_name)
        if wf_img and live_img:
            pairs.append((display_name, wf_name, live_name, wf_img, live_img))
            wf_paired.add(wf_name)
            live_paired.add(live_name)
        elif wf_img:
            wf_paired.add(wf_name)
            # Don't add to pairs but note it's paired-but-live-missing
        elif live_img:
            live_paired.add(live_name)

    # Static pairs
    for wf_name, live_name in STATIC_PAIRS:
        add_pair(wf_name, live_name, wf_name)

    # Inventory sub-tab pairs
    for i, wf_slug in enumerate(WF_INV_TABS_ORDERED):
        wf_key = f"inventory_tab_{wf_slug}"
        live_key = f"inventory_tab_{i}"
        add_pair(wf_key, live_key, wf_key)

    # Accounting sub-tab pairs
    # Live rail IDs (by index in ACC_RAIL_IDS): purchase(0), proforma(1),
    # ledger(2), sync(3), master(4), audit(5), wz(6), pz(7), pw(8), rw(9), mm(10)
    ACC_WF_TO_LIVE_IDX = {
        "overview":       0,   # purchase ledger — best overview match
        "proforma":       1,   # proforma rail
        "invoice":        None, # no dedicated invoice rail in live
        "credit_note":    None, # no dedicated credit-note rail in live
        "wz":             6,
        "pz":             7,
        "pw":             8,
        "rw":             9,
        "mm":             10,
        "client_balance": None, # no dedicated balance rail in live
        "client_ledger":  2,    # ledger rail
        "supplier_ledger":None, # no supplier ledger rail in live
        "wfirma_sync":    3,    # sync rail
    }
    for wf_slug, live_idx in ACC_WF_TO_LIVE_IDX.items():
        wf_key = f"accounting_tab_{wf_slug}"
        if live_idx is not None:
            live_key = f"accounting_tab_{live_idx}"
            add_pair(wf_key, live_key, wf_key)
        # else: no live counterpart — wf_key stays unpaired and appears in wf_only

    # Unpaired
    wf_only = [(k, v) for k, v in wf_screens.items() if k not in wf_paired]
    live_only = [(k, v) for k, v in live_screens.items() if k not in live_paired]

    return pairs, wf_only, live_only


# ── Index ──────────────────────────────────────────────────────────────────────

def write_index(pairs, wf_only, live_only, wf_errors, live_errors, idx_path: Path):
    lines = [
        "# CP3 Capture Index — Wave-3\n\n",
        f"**Generated:** {time.strftime('%Y-%m-%d %H:%M UTC')}\n",
        f"**Viewport:** {VIEWPORT['width']}x{VIEWPORT['height']}, light default\n\n",
        "## Summary\n\n",
        "| Category | Count |\n|---|---|\n",
        f"| Paired composites | {len(pairs)} |\n",
        f"| Wireframe-only | {len(wf_only)} |\n",
        f"| Live-only | {len(live_only)} |\n",
        f"| Wireframe errors | {len(wf_errors)} |\n",
        f"| Live errors | {len(live_errors)} |\n\n",
        "## Paired Composites\n\n",
        "| Pair # | Screen Name | Wireframe Source | Live Source | File |\n",
        "|---|---|---|---|---|\n",
    ]
    for num, (name, wf_name, live_name, _, _) in enumerate(pairs, 1):
        fname = f"pair-{num:02d}-{slugify(name)}.png"
        lines.append(f"| {num} | {name} | {wf_name} | {live_name} | [{fname}]({fname}) |\n")

    lines.append("\n## Wireframe-Only (Census tag: W4-PLANNED)\n\n")
    if wf_only:
        lines.append("| Name | File | Census Tag |\n|---|---|---|\n")
        for name, _ in wf_only:
            fname = f"only-wireframe-{slugify(name)}.png"
            lines.append(f"| {name} | [{fname}]({fname}) | W4-PLANNED |\n")
    else:
        lines.append("_None_\n")

    lines.append("\n## Live-Only (Census tag: W4-EXTRA)\n\n")
    if live_only:
        lines.append("| Name | File | Census Tag |\n|---|---|---|\n")
        for name, _ in live_only:
            fname = f"only-live-{slugify(name)}.png"
            lines.append(f"| {name} | [{fname}]({fname}) | W4-EXTRA |\n")
    else:
        lines.append("_None_\n")

    lines.append("\n## Capture Errors\n\n")
    all_errors = [(f"wireframe/{k}", v) for k, v in wf_errors.items()] + \
                 [(f"live/{k}", v) for k, v in live_errors.items()]
    if all_errors:
        lines.append("| Source/Screen | Error |\n|---|---|\n")
        for name, err in all_errors:
            lines.append(f"| {name} | {err} |\n")
    else:
        lines.append("_No errors_\n")

    idx_path.write_text("".join(lines), encoding="utf-8")
    print(f"\n  INDEX.md → {idx_path}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output:   {OUT_DIR}")
    print(f"Viewport: {VIEWPORT['width']}x{VIEWPORT['height']}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            executable_path=CHROME_PATH,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        wf_screens, wf_errors = capture_wireframe(browser)
        live_screens, live_errors = capture_live(browser)

        browser.close()

    print(f"\nWireframe screens: {len(wf_screens)}, errors: {len(wf_errors)}")
    print(f"Live screens:      {len(live_screens)}, errors: {len(live_errors)}")

    pairs, wf_only, live_only = build_pairs(wf_screens, live_screens)
    print(f"Pairs: {len(pairs)}  WF-only: {len(wf_only)}  Live-only: {len(live_only)}")

    # Save composites
    print("\n=== SAVING COMPOSITES ===")
    for num, (name, wf_name, live_name, wf_img, live_img) in enumerate(pairs, 1):
        fname = OUT_DIR / f"pair-{num:02d}-{slugify(name)}.png"
        try:
            composite = compose_side_by_side(wf_img, live_img)
            save_png(composite, fname)
        except Exception as e:
            print(f"    ERROR compositing pair {num} ({name}): {e}")

    # Save wireframe-only
    for name, img in wf_only:
        fname = OUT_DIR / f"only-wireframe-{slugify(name)}.png"
        try:
            save_png(img, fname)
        except Exception as e:
            print(f"    ERROR wf-only {name}: {e}")

    # Save live-only
    for name, img in live_only:
        fname = OUT_DIR / f"only-live-{slugify(name)}.png"
        try:
            save_png(img, fname)
        except Exception as e:
            print(f"    ERROR live-only {name}: {e}")

    # Write index
    write_index(pairs, wf_only, live_only, wf_errors, live_errors, OUT_DIR / "INDEX.md")

    print("\n" + "=" * 60)
    print("CP3 CAPTURE COMPLETE")
    print(f"  Paired composites : {len(pairs)}")
    print(f"  Wireframe-only    : {len(wf_only)}")
    print(f"  Live-only         : {len(live_only)}")
    print(f"  WF errors         : {len(wf_errors)}")
    print(f"  Live errors       : {len(live_errors)}")
    print(f"  Output dir        : {OUT_DIR}")

    if wf_errors:
        print("\nWireframe errors:")
        for k, v in wf_errors.items():
            print(f"  {k}: {v}")
    if live_errors:
        print("\nLive errors:")
        for k, v in live_errors.items():
            print(f"  {k}: {v}")

    return len(pairs), len(wf_only), len(live_only)


if __name__ == "__main__":
    main()
