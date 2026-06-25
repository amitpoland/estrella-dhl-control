"""
test_v2_babel_pin.py -- Regression guard for the /v2/ in-browser Babel boot pipeline.

ROOT-CAUSE THIS PINS
--------------------
/v2/index.html runs an in-browser Babel pipeline: every page is a
`<script type="text/babel">` that @babel/standalone fetches, compiles, and
appends to the document as a CLASSIC <script>.

The CDN fallback used to load `@babel/standalone/babel.min.js` UNPINNED (= latest).
When unpkg's "latest" advanced from Babel 7 -> Babel 8, the default
@babel/preset-react JSX runtime flipped from "classic" to "automatic". The
automatic runtime emits `import { jsx as _jsx } from "react/jsx-runtime"` at the
top of every compiled file. Appending that ESM `import` as a classic <script>
throws:

    Chrome : "Cannot use import statement outside a module"
    Safari : "import call expects one or two arguments. Unexpected token '{'"

...which the shell boot guard surfaces as "Estrella Atlas - JavaScript error".
No repo code changed; an UNPINNED CDN dependency drifted under the page.

These tests fail if anyone (a) reintroduces an unpinned @babel/standalone ref,
(b) bumps the pin to 8.x without switching to runtime:classic, (c) lets a CDN
React/ReactDOM ref go unpinned, or (d) introduces native ESM (`type="module"`
or a top-level `import`/`export`) into the classic text/babel shell.

Pure static assertions -- no Node/Babel runtime required (CI has neither).
"""
from __future__ import annotations

import pathlib
import re

_STATIC = pathlib.Path(__file__).parent.parent / "app" / "static"
_INDEX = _STATIC / "v2" / "index.html"
_VENDOR_SCRIPT = pathlib.Path(__file__).parent.parent / "scripts" / "download-v2-vendor.ps1"

# Any reference to the standalone Babel bundle, pinned or not.
_BABEL_REF = re.compile(r"@babel/standalone(?:@(?P<ver>[0-9][^/\"'\s]*))?/babel\.min\.js")


def _index_html() -> str:
    return _INDEX.read_text(encoding="utf-8", errors="replace")


def test_index_has_babel_reference() -> None:
    """Sanity: the shell still loads @babel/standalone (pipeline assumption holds)."""
    assert _BABEL_REF.search(_index_html()), "no @babel/standalone reference found in v2/index.html"


def test_babel_standalone_is_version_pinned_in_index() -> None:
    """Every @babel/standalone CDN ref must carry an explicit @<version> pin.

    An unpinned ref resolves to 'latest' and is exactly what let Babel 8 break boot.
    """
    for m in _BABEL_REF.finditer(_index_html()):
        assert m.group("ver"), (
            "Unpinned @babel/standalone reference in v2/index.html: "
            f"{m.group(0)!r}. Pin it to a 7.x version (e.g. @7.26.4)."
        )


def test_babel_standalone_pinned_to_v7_in_index() -> None:
    """The pin must be 7.x. Babel 8 defaults preset-react to the automatic JSX runtime,
    which injects an ESM import that cannot run in the classic text/babel pipeline."""
    refs = list(_BABEL_REF.finditer(_index_html()))
    assert refs, "no @babel/standalone reference found in v2/index.html"
    for m in refs:
        ver = m.group("ver") or ""
        major = ver.split(".")[0] if ver else ""
        assert major == "7", (
            f"@babel/standalone pinned to {ver!r} in v2/index.html. "
            "Only 7.x is compatible with the in-browser classic JSX runtime. "
            "Do NOT use 8.x without switching every text/babel tag to runtime:classic."
        )


def test_react_and_reactdom_cdn_refs_are_pinned_in_index() -> None:
    """React / ReactDOM CDN fallbacks must be version-pinned too (no bare 'latest')."""
    html = _index_html()
    for pkg in ("react", "react-dom"):
        # match unpkg refs like react@18 / react-dom@18 ; fail on a bare unpinned name.
        unpinned = re.search(rf"unpkg\.com/{re.escape(pkg)}/umd/", html)
        assert unpinned is None, f"Unpinned unpkg/{pkg} reference in v2/index.html"
        pinned = re.search(rf"unpkg\.com/{re.escape(pkg)}@\d", html)
        assert pinned, f"No version-pinned unpkg/{pkg}@<ver> reference in v2/index.html"


def test_vendor_download_script_pins_babel_v7() -> None:
    """The vendor pre-download script must fetch the SAME 7.x Babel as the CDN fallback,
    otherwise running it writes a Babel 8 local file that breaks boot the same way."""
    assert _VENDOR_SCRIPT.exists(), f"vendor download script missing at {_VENDOR_SCRIPT}"
    text = _VENDOR_SCRIPT.read_text(encoding="utf-8", errors="replace")
    refs = list(_BABEL_REF.finditer(text))
    assert refs, "download-v2-vendor.ps1 does not reference @babel/standalone"
    for m in refs:
        ver = m.group("ver") or ""
        assert ver.split(".")[0] == "7", (
            f"download-v2-vendor.ps1 babel pin is {ver!r}; must be 7.x to match index.html."
        )


def test_all_static_html_babel_refs_are_versioned() -> None:
    """No service/app/static/**/*.html file may load @babel/standalone without a version pin.

    An unpinned ref resolves to 'latest' on unpkg; when unpkg advanced to Babel 8 the
    default preset-react runtime flipped from classic to automatic, injecting ESM imports
    that crash in-browser classic text/babel pipelines.
    """
    unversioned = re.compile(r"unpkg\.com/@babel/standalone/babel\.min\.js")
    failures: list[str] = []
    for html_file in sorted(_STATIC.rglob("*.html")):
        try:
            text = html_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if unversioned.search(text):
            failures.append(str(html_file.relative_to(_STATIC)))
    assert not failures, (
        "Unversioned @babel/standalone CDN reference found in static HTML files "
        "(must pin to e.g. @7.26.4):\n  " + "\n  ".join(failures)
    )


def test_all_static_html_babel_pins_are_v7() -> None:
    """Every @babel/standalone pin in static HTML must be 7.x, not 8.x.

    Babel 8 preset-env defaults to ESM module output and preset-react defaults
    to the automatic JSX runtime.  Both produce `import` statements that cannot
    be injected as classic <script> blocks, triggering:
        "Cannot use import statement outside a module"
    Do NOT bump to 8.x without switching every text/babel tag to runtime:classic
    (data-presets='["react",{"runtime":"classic"}]') and verifying no preset-env
    module transform fires.
    """
    babel_versioned = re.compile(
        r"unpkg\.com/@babel/standalone@(?P<ver>[0-9][^/\"'\s]*)/babel\.min\.js"
    )
    failures: list[str] = []
    for html_file in sorted(_STATIC.rglob("*.html")):
        try:
            text = html_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in babel_versioned.finditer(text):
            ver = m.group("ver")
            major = ver.split(".")[0]
            if major != "7":
                rel = str(html_file.relative_to(_STATIC))
                failures.append(f"{rel}: @babel/standalone@{ver} — only 7.x is safe")
    assert not failures, (
        "@babel/standalone pinned to non-7.x in static HTML "
        "(do NOT use 8.x without switching to runtime:classic):\n  "
        + "\n  ".join(failures)
    )


def test_v2_shell_has_no_native_esm() -> None:
    """The shell pipeline is classic text/babel only. A `type="module"` script or a
    top-level `import`/`export` would not run through Babel and would crash boot."""
    html = _index_html()
    assert 'type="module"' not in html, (
        'v2/index.html contains a type="module" script -- the shell uses the classic '
        "text/babel pipeline; native ESM scripts will not execute."
    )
    # Top-level ESM statements anywhere in the inline shell markup are forbidden.
    for ln in html.splitlines():
        assert not re.match(r"\s*(import\s+[\w{*'\"]|export\s+(default|const|function|class|\{))", ln), (
            f"native ESM statement in v2/index.html shell: {ln.strip()[:80]!r}"
        )
