# PLUGINS.md — Atlas V2 Capability Registry: Plugins & External Integrations

**Generated:** 2026-06-06 · **Source:** session deferred-tools list + system-reminder plugin registry
**Canonical tree:** `C:\PZ-verify` · No product code modified.

> "Plugins" in this context means: marketplace plugins surfaced in the Claude Code session,
> external API integrations (bio-research, PDF viewer, design tools), and authentication-only
> plugins (not yet connected). Distinct from MCP connectors (CONNECTORS.md).

---

## Summary

| # | Plugin | Domain | EJ-applicable | Status | Classification |
|---|---|---|---|---|---|
| 1 | brand-voice family (5 subagents) | Marketing/brand | NO | Wrong domain | UNKNOWN |
| 2 | bio-research:biorxiv | Biomedical research | NO | Wrong domain | UNKNOWN |
| 3 | bio-research:c-trials | Clinical trials | NO | Wrong domain | UNKNOWN |
| 4 | bio-research:chembl | Drug database | NO | Wrong domain | UNKNOWN |
| 5 | bio-research:consensus | Academic search | NO | Wrong domain | UNKNOWN |
| 6 | PDF viewer | Document viewing | indirect | Available | SAFE_READ_ONLY |
| 7 | GitHub (auth-only) | Source control | YES (potential) | Auth not connected | PRODUCTION_RISK if connected |
| 8 | Linear (auth-only) | Issue tracking | YES (potential) | Auth not connected | SAFE_READ_ONLY if connected |
| 9 | Figma plugin (auth-only) | Design | indirect | Auth not connected | SAFE_READ_ONLY |
| 10 | Slack plugin (auth-only) | Communications | indirect | Auth not connected | WRITE_RISK if connected |
| 11 | Other auth-only plugins (15+) | Various | NO | Auth not connected | UNKNOWN |

---

## Connected / Active Plugins

---

### P1. brand-voice Family (5 subagents) — WRONG DOMAIN

| Field | Value |
|---|---|
| **Name** | `brand-voice:conversation-analysis`, `brand-voice:discover-brand`, `brand-voice:document-analysis`, `brand-voice:quality-assurance`, `brand-voice:content-generation` |
| **Source** | Marketplace plugin — `plugin:brand-voice` |
| **Purpose** | Brand voice analysis, guideline generation, content validation, content generation. Analyzes sales calls, documents, generates brand-aligned content. |
| **R/W level** | READ (analysis) + WRITE (content-generation) |
| **Production risk** | LOW for EJ (wrong domain) |
| **Classification** | UNKNOWN — wrong domain |
| **EJ-applicable** | **NO.** This plugin is for marketing/brand teams, not logistics/customs/accounting. |
| **Recommended use** | NEVER for Atlas V2 technical work. |
| **Forbidden use** | Do not dispatch brand-voice agents for any EJ customs, PZ, DHL, wFirma, or inventory work. |

---

### P2–P5. bio-research Plugins — WRONG DOMAIN

| Field | Value |
|---|---|
| **Names** | `plugin:bio-research:biorxiv`, `plugin:bio-research:c-trials`, `plugin:bio-research:chembl`, `plugin:bio-research:consensus` |
| **Purpose** | Academic research databases: bioRxiv preprints, ClinicalTrials.gov, ChEMBL drug database, Consensus academic search. |
| **Classification** | UNKNOWN — wrong domain |
| **EJ-applicable** | **NO.** Biomedical/pharmaceutical research tools. Not applicable to jewellery logistics. |
| **Recommended use** | NEVER for Atlas V2 work. |

---

### P6. PDF Viewer Plugin

| Field | Value |
|---|---|
| **Name** | `mcp__plugin_pdf-viewer_pdf__*` |
| **Purpose** | Display, interact with, read, and save PDFs. Interactive PDF manipulation. |
| **Tools available** | `display_pdf`, `interact`, `list_pdfs`, `poll_pdf_commands`, `read_pdf_bytes`, `save_pdf`, `submit_page_data`, `submit_save_data`, `submit_viewer_state` |
| **R/W level** | READ + limited WRITE (save) |
| **Production risk** | LOW |
| **Classification** | SAFE_READ_ONLY (read tasks) |
| **EJ-applicable** | YES — for reading customs documents (SAD, ZC429), packing lists, invoices. Supplemental to `document-intelligence` agent. |
| **Recommended use** | Reading customs/shipping PDFs during evidence extraction. Viewing generated Polish Description PDFs. |
| **Forbidden use** | Do not save PDF modifications to production storage paths without operator approval. |

---

## Authentication-Only Plugins (Not Yet Connected)

These plugins appear in the deferred tools list but only expose `authenticate` and
`complete_authentication` tools — they are NOT yet connected. Capabilities listed are
what they would provide once connected. Do not assume they are available.

| Plugin | EJ relevance | Would provide | Risk if connected |
|---|---|---|---|
| `plugin_engineering_github` | HIGH — PRs, issues, releases | GitHub API (repos, PRs, issues, commits, releases, checks) | PRODUCTION_RISK (can push, merge, modify repo) |
| `plugin_engineering_linear` | MEDIUM — issue tracking | Linear issues, projects, cycles, roadmaps | SAFE_READ_ONLY / WRITE_RISK (write issues) |
| `plugin_engineering_datadog` | LOW | Metrics, logs, monitors, alerts | SAFE_READ_ONLY |
| `plugin_engineering_pagerduty` | LOW | Incidents, alerts, on-call | SAFE_READ_ONLY / WRITE_RISK (acknowledge) |
| `plugin_operations_atlassian` | LOW | Jira/Confluence | SAFE_READ_ONLY / WRITE_RISK |
| `plugin_operations_notion` | LOW | Notion pages/databases | SAFE_READ_ONLY / WRITE_RISK |
| `plugin_operations_slack` | MEDIUM | Slack messages/channels | WRITE_RISK (sends real messages) |
| `plugin_operations_ms365` | LOW | Microsoft 365 (email, calendar, OneDrive) | WRITE_RISK |
| `plugin_operations_asana` | LOW | Asana tasks/projects | SAFE_READ_ONLY / WRITE_RISK |
| `plugin_design_figma` | LOW | Figma (overlaps CN12) | SAFE_READ_ONLY / WRITE_RISK |
| `plugin_design_intercom` | LOW | Customer support | WRITE_RISK |
| `plugin_data_amplitude` | LOW | Analytics | SAFE_READ_ONLY |
| `plugin_data_bigquery` | LOW | BigQuery SQL | SAFE_READ_ONLY / WRITE_RISK |
| `plugin_data_hex` | LOW | Hex notebooks | SAFE_READ_ONLY / WRITE_RISK |
| `plugin_data_definite` | LOW | Data analytics | SAFE_READ_ONLY |
| `plugin_legal_egnyte` | LOW | Document management | SAFE_READ_ONLY |
| `plugin_product-management_clickup` | LOW | ClickUp tasks | WRITE_RISK |
| `plugin_product-management_monday` | LOW | Monday.com | WRITE_RISK |
| `plugin_product-management_pendo` | LOW | Product analytics | SAFE_READ_ONLY |
| `plugin_product-management_similarweb` | LOW | Web traffic analytics | SAFE_READ_ONLY |
| `plugin_brand-voice_box` | LOW | Box file storage | SAFE_READ_ONLY / WRITE_RISK |
| `plugin_brand-voice_gong` | LOW | Gong sales calls | SAFE_READ_ONLY |
| `plugin_brand-voice_granola` | LOW | Meeting notes | SAFE_READ_ONLY |

---

## Priority Connection Candidates

If any of the auth-only plugins should be connected for Atlas V2 work, the candidates are:

| Priority | Plugin | Rationale | Risk note |
|---|---|---|---|
| P1 | `plugin_engineering_github` | Direct GitHub integration for PRs/issues (currently using `gh` CLI via Bash) | PRODUCTION_RISK — must never auto-push/auto-merge; operator gate required |
| P2 | `plugin_engineering_linear` | Issue tracking for GATE 4 salvage filings | Low risk if read-only |

All other plugins are non-applicable to Atlas V2 logistics/customs/accounting work.

---

## Plugin Safety Rules

1. **Brand-voice and bio-research plugins are noise** for EJ Atlas V2 work. Their presence in the
   dispatch menu is registry clutter. Never activate them for EJ tasks.
2. **Auth-only plugins = no capability until authenticated.** Do not assume these tools work —
   test the auth flow explicitly before depending on them.
3. **GitHub plugin (if connected) is high-risk.** It can create branches, push commits, merge PRs.
   All GATE 1 + GATE 2 rules apply even when using a GitHub plugin.
4. **Scheduled Tasks plugin** (in CONNECTORS.md CN20) is classified as a plugin by the system but
   governs real Windows scheduling — treat at PRODUCTION_RISK level.
