# Sprint 22 — API Status V2

**Campaign:** Atlas-V2  
**Sprint:** 22 of 23  
**Branch:** `atlas-v2/sprint-22-api-status-v2`  
**Dependency:** Sprints 11 (admin) + 16 (carriers) merged  
**New file:** `service/app/static/api-status-v2.html`  
**URL:** `/dashboard/api-status-v2.html`  
**Design source:** `design-files/api-status-page.jsx`

---

## Authority Boundary

```
OWNS:  Consolidated API health surface — KPI strip, integration cards
       (carriers, wFirma, customs, internal, webhooks), endpoint registry
       (searchable), recent errors panel, incidents log, synthetic-probe trigger
NEVER: Carrier credential management (carriers-v2), system writes (admin-v2),
       incident resolution actions (incidents are read-only display here)
```

This is the operator's single pane to verify "is anything wrong with our integrations
right now". It consolidates surfaces previously scattered across Diagnostics, Carriers,
Admin, module footers.

---

## APIs

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/admin/api-status` | Aggregated health | NEW |
| `GET /api/v1/admin/api-status/endpoints` | Endpoint registry | NEW |
| `GET /api/v1/admin/api-status/errors` | Recent errors (read-only) | NEW |
| `GET /api/v1/admin/api-status/incidents` | Incident log (read-only) | NEW |
| `POST /api/v1/admin/api-status/{id}/test` | Synthetic probe (no-op write) | NEW |

`security-permissions` verdict: admin-role gating on all endpoints. `backend-safety-reviewer`
verdicts that probe POST is truly no-op (no carrier state mutation).

---

## Page Structure

- PageHeader (h1: "API Status", subtitle: "Integration health")
- KPI strip: total integrations, healthy %, calls 24h, errors 24h, avg latency
- Integration cards grid: per-integration card (state Badge, endpoints count, success %, latency, last error)
- Endpoint registry: searchable CompactTable (path, method, group, success%, latency)
- Recent errors panel: timeline of last 50 errors
- Incidents log: chronological list, read-only
- "Probe" Btn per integration (no-op write only)
- SessionBanner on auth/permission errors

---

## Mandatory Agents

Same 15. Adds:
- `security-permissions` verdict on admin-role gating
- `security-write-action-reviewer` verdict on probe POST (no state mutation)
- `compliance` verdict on incident-log retention/exposure

---

## Acceptance Criteria

1. Page loads, all sections render
2. Admin-role required — non-admin sees PermissionDenied banner
3. KPI strip reflects real values
4. Endpoint registry searchable
5. Probe Btn returns latency, does NOT mutate carrier state
6. Errors + incidents panels read-only
7. SessionBanner on permission errors
8. `data-testid` everywhere
9. Rollback: remove file

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 22 — API Status V2
Branch: atlas-v2/sprint-22-api-status-v2 (Sprints 11 + 16 merged)

STACK CONSTRAINTS: same as Sprint 14.
Design ref: git show origin/atlas-v2/source-bundle:design-files/api-status-page.jsx

TASK: Create api-status-v2.html — consolidated API health surface.

AUTHORITY:
OWNS: aggregated health, endpoint registry, recent errors, incidents, synthetic probe
NEVER: credential management (carriers-v2), system writes (admin-v2),
       incident resolution actions

SECURITY:
- security-permissions verdict: admin-role required for all endpoints
- security-write-action-reviewer verdict: probe POST is no-op (no carrier mutation)

BACKEND: 4 GETs + 1 no-op POST. backend-safety-reviewer verdicts.

GATE 2 + 15-agent sequence + test baseline: same as Sprint 14.

End with /deploy after merge.
```
