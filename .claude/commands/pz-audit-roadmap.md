# /pz-audit-roadmap

Scan the full Estrella PZ codebase and produce a decision-ready audit roadmap. Do NOT modify any files. Only inspect and report.

## Instructions

You are performing a read-only codebase audit. Follow every step below exactly. Do not skip sections. Do not make assumptions — verify by reading actual files.

---

### Step 1 — Map the full file tree

Read the directory structure of:
- `/Users/amitgupta/Downloads/CLI/service/app/` (FastAPI app)
- `/Users/amitgupta/Downloads/CLI/service/app/api/` (all route files)
- `/Users/amitgupta/Downloads/CLI/service/app/static/` (all HTML/JS/CSS)
- `/Users/amitgupta/Downloads/CLI/service/app/services/` (service layer)
- `/Users/amitgupta/Downloads/CLI/service/app/auth/` (auth layer)
- `/Users/amitgupta/Downloads/CLI/` (engine files: pz_*.py, audit_*.py, etc.)
- `/Users/amitgupta/Downloads/CLI/service/deploy-pz.sh`
- `/Users/amitgupta/Library/LaunchAgents/eu.estrellajewels.pz-service.plist` (if exists)

List every file found. Note anything missing that would be expected.

---

### Step 2 — Audit each feature domain

For each domain below, read the relevant files and determine the actual implementation state.

**Use these status values only:**
- `COMPLETE` — fully implemented, wired end-to-end, stable
- `PARTIAL` — code exists but not fully wired (e.g. backend exists, UI does not call it; or route exists, frontend ignores it)
- `BROKEN` — code exists, is wired, but produces wrong output or errors
- `PLANNED NOT IMPLEMENTED` — discussed in CLAUDE.md/comments but no code found
- `NEEDS TESTING` — looks complete but has not been verified with real shipment data
- `DEPRECATED` — code present but intentionally superseded or no longer used

**Risk levels:**
- `HIGH` — blocks production shipment processing, or is a security vulnerability
- `MEDIUM` — incomplete business feature that affects daily operations
- `LOW` — UI polish, nice-to-have, non-blocking

#### Domains to audit:

1. **FastAPI routes** — Read all files in `app/api/`. List every router, every endpoint (method + path), its auth dependency, and whether the corresponding UI or caller exists.

2. **Dashboard UI** — Read `app/static/dashboard.html` and `app/static/batch.html`. List every section/panel/tab/button and check whether its backing API endpoint exists and returns the expected data shape.

3. **Batch upload form** — Check `batch.html` upload form: file input types accepted, drag-drop, multi-file, progress indicator, validation before submit.

4. **Cliq command handlers** — Read `app/api/routes_bot.py`. List every command/webhook handler. Check what it does, what it posts back, and whether the format matches CLAUDE.md spec.

5. **Batch/session manager** — Read `app/services/batch_manager.py`. Check: session lifecycle, auto-submit logic, expiry callbacks, test session clearing, sweep interval.

6. **WorkDrive sync** — Read `app/services/export_service.py` WorkDrive section. Check: YYYY/MM/batch folder structure, source file copying, audit.json patching, error handling, retry on sync failure.

7. **Audit report generation** — Check `audit_agent.py`, `audit_pdf.py`, `audit_scoring.py`. Verify: EN report, PL report, memo PDF, score field, risk_level field, failed_checks list. Check whether `export_service.py` correctly generates all 3 and patches `audit_generation_status` into audit.json.

8. **Correction engine** — Read `correction_engine.py`. Check: correction schema version, what corrections are applied, whether `corrections_BATCH_ID.json` is generated and exposed via API.

9. **Authentication / login / signup** — Read `app/auth/`, `app/api/routes_auth.py`, `app/static/login.html`, `app/static/signup.html`. Check: bcrypt hashing, JWT in HttpOnly cookie, session expiry, login blocked for pending/rejected users, first-user bootstrap, CSRF considerations.

10. **Admin approval flow** — Read `app/api/routes_admin.py`, `app/static/admin-users.html`. Check: pending/approved/rejected tabs, approve/reject/disable/role endpoints, email queue trigger, admin-only route guard in both backend and frontend.

11. **Email / MCP integration** — Read `app/services/email_service.py`, `app/api/routes_admin.py` email-queue endpoints. Check: queue JSON path, queue_email() function, make_approval_email() / make_rejection_email(), get_pending_emails(), mark_sent(). Verify whether Claude MCP actually sends from `info@estrellajewels.eu` or whether that step is manual.

12. **DHL / FedEx tracking** — Search all files for tracking number detection, carrier detection logic, AWB parsing. Check `routes_dashboard.py` `_detect_carrier()`. Check whether tracking links are generated and shown in UI.

13. **Art.33a detection** — Search for `art33a`, `art_33a`, `settlement_mode`. Check: CLI flag `--settlement-mode art33a`, note 4 logic in engine, whether dashboard surfaces the mode, whether Cliq posting mentions it.

14. **NBP / exchange rate parsing** — Check `pz_import_processor.py` or `pz_calculator.py` for NBP table fetch, rate extraction, date parsing, error fallback. Check whether `nbp` block appears in audit.json.

15. **Invoice quantity / product breakdown** — Check parsing of PCS, CTN, SET quantities. Check `qty_match_by_type` in verification dict. Check how `batch.html` renders quantity verification.

16. **SAD / ZC429 parsing** — Check what fields are extracted: MRN, LRN, clearance date, exporter, importer, CIF value, duty (A00), VAT (B00), item count. Check `verification` dict for what is actually verified vs None.

17. **Source document visibility** — Check `_build_source_files()` in `routes_dashboard.py`. Check whether source invoices, SAD, AWB are listed and downloadable in the UI.

18. **Generated document links** — Check that PZ PDF, XLSX, audit EN, audit PL, audit memo, corrections JSON all have working download URLs (absolute HTTPS, not localhost). Check `FASTAPI_PUBLIC_URL` in settings.

19. **Delete / reprocess / draft actions** — Check `DELETE /api/v1/batches/{id}` soft-delete. Check whether reprocess, edit, or draft actions exist. Check UI buttons in dashboard.

20. **Guardian health endpoints** — Check `app/api/routes_debug.py` or wherever `/api/v1/health` lives. Check what it returns. Check whether engine health check is wired. Check `RUN_VERIFY_ON_STARTUP` flag.

21. **Launchd / deploy scripts** — Read `deploy-pz.sh`. Check: engine files synced, venv path, plist path, health check loop. Read plist file if accessible. Check whether all current engine modules are in the deploy loop.

22. **Zoho token auto-refresh** — Search for OAuth token refresh logic in `routes_bot.py`, `.env`, settings. Check whether the Cliq webhook uses a static token or OAuth with refresh.

23. **Role-based access control** — Check: admin role guard on `/admin/users`, admin-only API endpoints, whether non-admin users can reach admin routes, whether role is stored in JWT or DB, whether frontend checks role before showing admin nav link.

---

### Step 3 — Produce the audit report

Output exactly this structure:

---

## PZ Codebase Audit — [date]

### Feature Table

| Feature | Status | Files Involved | What Works | What Is Broken / Missing | Risk | Recommended Next Action |
|---------|--------|---------------|-----------|--------------------------|------|------------------------|
(one row per feature domain, 23 rows total)

---

### Section 1 — Production-Critical Broken Items
*Items that block daily shipment processing right now.*

List each as:
**[Feature name]** — [one sentence on what is broken and why it blocks production]

---

### Section 2 — Business Dashboard Gaps
*Missing or broken UI/UX/display items that affect daily operations.*

---

### Section 3 — Audit / Compliance Gaps
*Missing audit reports, Art.33a, NBP, quantity checks, exporter/importer mapping.*

---

### Section 4 — Integration Gaps
*Zoho Cliq, WorkDrive, email, DHL/FedEx, OAuth, MCP issues.*

---

### Section 5 — Security / Authentication Gaps
*Login/signup, approval, role access, session security.*

---

### Section 6 — Completed Stable Modules
*What is working and should NOT be changed.*

---

### Section 7 — Recommended Implementation Order

Top 10 next actions in priority order. Format:

1. **[Action title]** — [one sentence on what to implement and why it is the highest priority]
2. ...

---

**Which item should I implement next?**

---

## Rules (enforced throughout)

- Read actual files. Do not invent status from memory.
- If a feature was discussed in CLAUDE.md but no code exists: `PLANNED NOT IMPLEMENTED`.
- If backend exists but UI does not call it: `PARTIAL`.
- If UI renders something but backend does not produce the data: `BROKEN`.
- If looks complete but no real shipment tested it: `NEEDS TESTING`.
- Do not change any customs calculation logic.
- Do not change any business rules.
- Do not modify any files.
- Return only the audit report.
