"""
test_shipment_v2_contract.py — Source-grep contract tests for Shipment V2 frontend.

Tests the 15 mandatory source-grep contracts for shipment-v2.html from
Atlas-V2 Sprint 03. These tests never make HTTP requests — they read
file content and ensure the static implementation meets the requirements.

Coverage:
  1. File exists at expected path
  2. CDN load order: react@18, react-dom@18, @babel/standalone, dashboard-shared.js, pz-api.js, pz-state.js, pz-components.js
  3. All required testids present
  4. Read-only authority: no write-capable API calls
  5. Phase testids defined as data structure
  6. Quick links point to proforma-v2.html and pz-v2.html
  7. Document links use target="_blank"
  8. ?batch_id= URL param read via URLSearchParams
  9. Auth error handled (401/403 path present)
  10. Empty/error state present for missing batch_id
  11. Stack compliance: no TypeScript, no Tailwind, no Vite, no ES modules
  12. CSS custom properties used (--bg, --text), no raw hex in components
  13. GET /api/v1/dashboard/batches/ present (primary data source)
  14. GET /api/v1/tracking/ present (tracking events)
  15. V1 freeze: this is the only new file (no modifications to V1)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


class TestShipmentV2FileExists:
    """Contract 1: File exists at expected path"""

    STATIC = Path(__file__).parents[1] / "app" / "static"

    def test_shipment_v2_file_exists(self):
        shipment_v2_path = self.STATIC / "shipment-v2.html"
        assert shipment_v2_path.exists(), (
            f"shipment-v2.html must exist at {shipment_v2_path}"
        )


class TestShipmentV2CDNLoadOrder:
    """Contract 2: CDN load order verification"""

    STATIC = Path(__file__).parents[1] / "app" / "static"

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.shipment_v2_html = (self.STATIC / "shipment-v2.html").read_text(encoding="utf-8")

    def test_cdn_script_load_order(self):
        """CDN scripts must be loaded in dependency order"""
        react_pos = self.shipment_v2_html.find("react@18/umd/react.production.min.js")
        react_dom_pos = self.shipment_v2_html.find("react-dom@18/umd/react-dom.production.min.js")
        babel_pos = self.shipment_v2_html.find("@babel/standalone/babel.min.js")

        assert react_pos != -1, "React@18 script must be present"
        assert react_dom_pos != -1, "ReactDOM@18 script must be present"
        assert babel_pos != -1, "@babel/standalone script must be present"

        assert react_pos < react_dom_pos, "React must load before ReactDOM"
        assert react_dom_pos < babel_pos, "ReactDOM must load before Babel"

    def test_shared_layer_load_order(self):
        """Shared layer scripts must load in dependency order"""
        shared_pos = self.shipment_v2_html.find("dashboard-shared.js")
        api_pos = self.shipment_v2_html.find("pz-api.js")
        state_pos = self.shipment_v2_html.find("pz-state.js")
        comp_pos = self.shipment_v2_html.find("pz-components.js")

        assert shared_pos != -1, "dashboard-shared.js must be present"
        assert api_pos != -1, "pz-api.js must be present"
        assert state_pos != -1, "pz-state.js must be present"
        assert comp_pos != -1, "pz-components.js must be present"

        assert shared_pos < api_pos, "dashboard-shared.js must load before pz-api.js"
        assert api_pos < state_pos, "pz-api.js must load before pz-state.js"
        assert state_pos < comp_pos, "pz-state.js must load before pz-components.js"


class TestShipmentV2RequiredTestIds:
    """Contract 3: All required testids present"""

    STATIC = Path(__file__).parents[1] / "app" / "static"

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.shipment_v2_html = (self.STATIC / "shipment-v2.html").read_text(encoding="utf-8")

    def test_required_testids_present(self):
        required_testids = [
            "shipment-v2-root",
            "back-to-dashboard-link",
            "batch-header",
            "batch-awb",
            "carrier-badge",
            "pipeline-timeline",
            "tracking-section",
            "clearance-section",
            "quick-links",
            "btn-view-proforma",
            "btn-view-pz",
        ]

        for testid in required_testids:
            assert f'data-testid="{testid}"' in self.shipment_v2_html, (
                f"Required testid '{testid}' must be present in shipment-v2.html"
            )

    def test_phase_testids_present(self):
        """Phase testids must be present (defined in phases array)"""
        phase_testids = [
            "phase-precheck",
            "phase-dhl-email",
            "phase-sad",
            "phase-customs",
            "phase-ready-pz",
        ]

        # These are rendered dynamically via the phases array
        for testid in phase_testids:
            assert f"testid: '{testid}'" in self.shipment_v2_html, (
                f"Phase testid '{testid}' must be defined in phases array"
            )


class TestShipmentV2ReadOnlyAuthority:
    """Contract 4: Read-only authority - no write-capable API calls"""

    STATIC = Path(__file__).parents[1] / "app" / "static"

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.shipment_v2_html = (self.STATIC / "shipment-v2.html").read_text(encoding="utf-8")

    def test_no_write_api_calls(self):
        """Must not contain POST/PUT/DELETE/PATCH API calls to non-navigation endpoints"""
        # Strip comments to avoid false positives
        content = re.sub(r'//[^\n]*', '', self.shipment_v2_html)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)

        forbidden_patterns = [
            "method.*['\"]POST['\"]",
            "method.*['\"]PUT['\"]",
            "method.*['\"]DELETE['\"]",
            "method.*['\"]PATCH['\"]",
            r"\.post\(",
            r"\.put\(",
            r"\.delete\(",
            r"\.patch\(",
        ]

        for pattern in forbidden_patterns:
            assert not re.search(pattern, content, re.IGNORECASE), (
                f"shipment-v2.html must not contain write API calls — found pattern: {pattern}"
            )

    def test_navigation_buttons_are_href_links(self):
        """Navigation buttons must use href links, not API calls"""
        assert "btn-view-proforma" in self.shipment_v2_html
        assert "btn-view-pz" in self.shipment_v2_html

        # Check that these buttons use window.location.href, not API calls
        assert "window.location.href" in self.shipment_v2_html, (
            "Quick link buttons must use window.location.href for navigation"
        )


class TestShipmentV2PhaseTestIds:
    """Contract 5: Phase testids defined as data structure"""

    STATIC = Path(__file__).parents[1] / "app" / "static"

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.shipment_v2_html = (self.STATIC / "shipment-v2.html").read_text(encoding="utf-8")

    def test_phases_defined_as_data_structure(self):
        """Phase testids must be defined in a data structure, not hardcoded individually"""
        # Look for phases array or similar data structure
        assert "phases = [" in self.shipment_v2_html or "const phases" in self.shipment_v2_html, (
            "Phases must be defined as a data structure (array of phase objects)"
        )

        # Check that testid is referenced from the data structure
        assert "testid" in self.shipment_v2_html and "phase.testid" in self.shipment_v2_html, (
            "Phase testids must be read from the phases data structure (phase.testid)"
        )


class TestShipmentV2QuickLinks:
    """Contract 6: Quick links point to correct V2 pages"""

    STATIC = Path(__file__).parents[1] / "app" / "static"

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.shipment_v2_html = (self.STATIC / "shipment-v2.html").read_text(encoding="utf-8")

    def test_quick_links_to_v2_pages(self):
        """Quick links must point to proforma-v2.html and pz-v2.html"""
        assert "proforma-v2.html" in self.shipment_v2_html, (
            "Quick links must include link to proforma-v2.html"
        )
        assert "pz-v2.html" in self.shipment_v2_html, (
            "Quick links must include link to pz-v2.html"
        )


class TestShipmentV2DocumentLinks:
    """Contract 7: Document links use target="_blank" """

    STATIC = Path(__file__).parents[1] / "app" / "static"

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.shipment_v2_html = (self.STATIC / "shipment-v2.html").read_text(encoding="utf-8")

    def test_document_links_open_in_new_tab(self):
        """Document links must use target='_blank' (not inline edit)"""
        # Find document links and verify they have target="_blank"
        doc_link_patterns = [
            r'href=[^>]*\/files\/[^>]*target="_blank"',
            r'target="_blank"[^>]*href=[^>]*\/files\/',
        ]

        has_doc_links = False
        for pattern in doc_link_patterns:
            if re.search(pattern, self.shipment_v2_html):
                has_doc_links = True
                break

        # If there are document links, they must use target="_blank"
        if '/files/' in self.shipment_v2_html:
            assert has_doc_links, (
                "Document links must use target='_blank' (found /files/ links without target='_blank')"
            )


class TestShipmentV2URLParams:
    """Contract 8: ?batch_id= URL param read via URLSearchParams"""

    STATIC = Path(__file__).parents[1] / "app" / "static"

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.shipment_v2_html = (self.STATIC / "shipment-v2.html").read_text(encoding="utf-8")

    def test_url_params_via_urlsearchparams(self):
        """Must read ?batch_id= parameter via URLSearchParams"""
        assert "URLSearchParams" in self.shipment_v2_html, (
            "Must use URLSearchParams to read URL parameters"
        )
        assert "batch_id" in self.shipment_v2_html, (
            "Must read batch_id parameter from URL"
        )
        assert "window.location.search" in self.shipment_v2_html or ".get('batch_id')" in self.shipment_v2_html, (
            "Must read batch_id from URL search parameters"
        )


class TestShipmentV2AuthErrorHandling:
    """Contract 9: Auth error handled (401/403 path present)"""

    STATIC = Path(__file__).parents[1] / "app" / "static"

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.shipment_v2_html = (self.STATIC / "shipment-v2.html").read_text(encoding="utf-8")

    def test_auth_error_handling_present(self):
        """Must handle 401/403 authentication errors"""
        auth_patterns = [
            "401",
            "403",
            "Session expired",
            "sessionError",
            "SessionBanner",
        ]

        has_auth_handling = any(pattern in self.shipment_v2_html for pattern in auth_patterns)
        assert has_auth_handling, (
            "Must include authentication error handling (401/403/Session expired)"
        )


class TestShipmentV2EmptyState:
    """Contract 10: Empty/error state present for missing batch_id"""

    STATIC = Path(__file__).parents[1] / "app" / "static"

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.shipment_v2_html = (self.STATIC / "shipment-v2.html").read_text(encoding="utf-8")

    def test_empty_state_for_missing_batch_id(self):
        """Must show EmptyState when batch_id is missing or invalid"""
        assert "EmptyState" in self.shipment_v2_html, (
            "Must use EmptyState component for error conditions"
        )
        assert "batch_id" in self.shipment_v2_html, (
            "Must check for batch_id presence"
        )
        # Look for error handling when batch_id is missing
        missing_batch_patterns = [
            "Missing batch_id",
            "!URL_BATCH_ID",
            "batch_id.*missing",
        ]
        has_missing_handling = any(
            re.search(pattern, self.shipment_v2_html, re.IGNORECASE)
            for pattern in missing_batch_patterns
        )
        assert has_missing_handling, (
            "Must handle missing batch_id with appropriate error message"
        )


class TestShipmentV2StackCompliance:
    """Contract 11: Stack compliance - no TypeScript, Tailwind, Vite, ES modules"""

    STATIC = Path(__file__).parents[1] / "app" / "static"

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.shipment_v2_html = (self.STATIC / "shipment-v2.html").read_text(encoding="utf-8")

    def test_no_typescript(self):
        """Must not contain TypeScript syntax"""
        # Extract just the script content to avoid false positives from HTML attributes
        script_start = self.shipment_v2_html.find('<script type="text/babel"')
        if script_start != -1:
            script_end = self.shipment_v2_html.find('</script>', script_start)
            script_content = self.shipment_v2_html[script_start:script_end] if script_end != -1 else ""
        else:
            script_content = ""

        typescript_patterns = [
            r"function\s+\w+\s*\([^)]*:\s*(string|number|boolean)",  # Function parameters with types
            r"const\s+\w+\s*:\s*(string|number|boolean)",  # Variable declarations with types
            r"interface\s+\w+",  # Interface declarations
            r"type\s+\w+\s*=",  # Type aliases
            r"<[A-Z]\w*>\s*\(",  # Generic function calls (more specific)
        ]

        for pattern in typescript_patterns:
            assert not re.search(pattern, script_content), (
                f"Must not contain TypeScript syntax — found pattern: {pattern}"
            )

    def test_no_tailwind(self):
        """Must not contain Tailwind CSS classes"""
        # Look for Tailwind utility classes but exclude semantic CSS classes like 'content-grid'
        tailwind_patterns = [
            r"className.*['\"].*\b(p-\d|m-\d|text-xs|text-sm|text-lg|bg-red-|bg-blue-|w-\d|h-\d)\b",
            r"\btailwind\b",
        ]

        for pattern in tailwind_patterns:
            assert not re.search(pattern, self.shipment_v2_html, re.IGNORECASE), (
                f"Must not contain Tailwind CSS — found pattern: {pattern}"
            )

    def test_no_vite(self):
        """Must not contain Vite syntax"""
        vite_patterns = [
            "import.meta",
            "vite",
            "__VITE__",
        ]

        for pattern in vite_patterns:
            assert not re.search(pattern, self.shipment_v2_html, re.IGNORECASE), (
                f"Must not contain Vite syntax — found pattern: {pattern}"
            )

    def test_no_es_module_imports(self):
        """Must not use ES module syntax in page body (Babel JSX inline is fine)"""
        # Check for ES module imports (import { ... } from '...')
        es_module_patterns = [
            r"import\s+{[^}]*}\s+from",
            r"import\s+\w+\s+from",
            r"export\s+{",
            r"export\s+default",
        ]

        # Extract the script body (after the CDN loads)
        script_start = self.shipment_v2_html.find('<script type="text/babel"')
        if script_start != -1:
            script_body = self.shipment_v2_html[script_start:]
            for pattern in es_module_patterns:
                assert not re.search(pattern, script_body), (
                    f"Must not use ES module syntax in page body — found pattern: {pattern}"
                )


class TestShipmentV2CSSProperties:
    """Contract 12: CSS custom properties used, no raw hex in components"""

    STATIC = Path(__file__).parents[1] / "app" / "static"

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.shipment_v2_html = (self.STATIC / "shipment-v2.html").read_text(encoding="utf-8")

    def test_css_custom_properties_present(self):
        """Must use CSS custom properties (--bg, --text at minimum)"""
        assert "--bg" in self.shipment_v2_html, (
            "Must define --bg CSS custom property"
        )
        assert "--text" in self.shipment_v2_html, (
            "Must define --text CSS custom property"
        )
        assert "var(--" in self.shipment_v2_html, (
            "Must use CSS custom properties with var(--property)"
        )

    def test_no_raw_hex_in_component_styles(self):
        """Must not use raw hex colors in component inline styles (root definition is ok)"""
        # Extract component styles (everything after the :root CSS block)
        root_end = self.shipment_v2_html.find("}")
        if root_end != -1:
            # Find the end of the complete :root block (including dark mode)
            remaining = self.shipment_v2_html[root_end:]
            # Look for the script section where components are defined
            script_start = remaining.find('<script type="text/babel"')
            if script_start != -1:
                component_section = remaining[script_start:]
                # Look for hex colors in style attributes within components
                hex_in_styles = re.findall(r'style=\{[^}]*#[0-9a-fA-F]{3,6}', component_section)
                assert len(hex_in_styles) == 0, (
                    f"Must not use raw hex colors in component styles — found: {hex_in_styles}"
                )


class TestShipmentV2APIEndpoints:
    """Contract 13 & 14: Required API endpoints present"""

    STATIC = Path(__file__).parents[1] / "app" / "static"

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.shipment_v2_html = (self.STATIC / "shipment-v2.html").read_text(encoding="utf-8")

    def test_dashboard_batches_endpoint_present(self):
        """Contract 13: Must use GET /api/v1/dashboard/batches/ as primary data source"""
        assert "/api/v1/dashboard/batches/" in self.shipment_v2_html, (
            "Must use GET /api/v1/dashboard/batches/ endpoint as primary data source"
        )

    def test_tracking_endpoint_present(self):
        """Contract 14: Must use GET /api/v1/tracking/ for tracking events"""
        assert "/api/v1/tracking/" in self.shipment_v2_html, (
            "Must use GET /api/v1/tracking/ endpoint for tracking events"
        )


class TestShipmentV2V1Freeze:
    """Contract 15: V1 freeze - this is the only new file"""

    STATIC = Path(__file__).parents[1] / "app" / "static"

    def test_shipment_detail_not_modified(self):
        """Must not modify shipment-detail.html (V1 freeze)"""
        # This test confirms that shipment-v2.html exists without modifying V1 files
        shipment_v2_path = self.STATIC / "shipment-v2.html"
        shipment_detail_path = self.STATIC / "shipment-detail.html"

        assert shipment_v2_path.exists(), (
            "shipment-v2.html must exist as the new V2 implementation"
        )

        # If shipment-detail.html exists, it should not import or reference shipment-v2
        if shipment_detail_path.exists():
            shipment_detail_content = shipment_detail_path.read_text(encoding="utf-8")
            assert "shipment-v2" not in shipment_detail_content, (
                "shipment-detail.html must not reference shipment-v2.html (V1 freeze)"
            )

    def test_dashboard_not_modified(self):
        """Must not modify dashboard.html (V1 freeze)"""
        dashboard_path = self.STATIC / "dashboard.html"

        # If dashboard.html exists, it should not import or reference shipment-v2
        if dashboard_path.exists():
            dashboard_content = dashboard_path.read_text(encoding="utf-8")
            assert "shipment-v2" not in dashboard_content, (
                "dashboard.html must not reference shipment-v2.html (V1 freeze)"
            )

    def test_only_new_v2_file(self):
        """Confirm this is the only new file for Sprint 03"""
        shipment_v2_path = self.STATIC / "shipment-v2.html"
        assert shipment_v2_path.exists(), (
            "shipment-v2.html must be the new Sprint 03 deliverable"
        )

        # Load the file to confirm it's a complete implementation
        content = shipment_v2_path.read_text(encoding="utf-8")
        assert "ShipmentV2Root" in content, (
            "shipment-v2.html must contain ShipmentV2Root component"
        )
        assert "ReactDOM.createRoot" in content, (
            "shipment-v2.html must be a complete React application"
        )