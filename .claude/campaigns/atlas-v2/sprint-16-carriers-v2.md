# Sprint 16 — Carriers V2

**Campaign:** Atlas-V2  
**Sprint:** 16 of 23  
**Branch:** `atlas-v2/sprint-16-carriers-v2`  
**Dependency:** Sprint 02 merged  
**New file:** `service/app/static/carriers-v2.html`  
**URL:** `/dashboard/carriers-v2.html`  
**Design source:** `design-files/carriers-page.jsx`

---

## Authority Boundary

```
OWNS:  Carrier integration registry display (DHL, FedEx, UPS, GLS, etc.),
       connection status, webhook health, supported services, audit log view,
       "Test connection" probe trigger (read-only ping)
NEVER: Credential storage in frontend, OAuth secret handling, real credential
       rotation (credentials live in backend secret store + admin endpoints),
       carrier disconnection (operator must use admin-v2 or backend CLI)
```

**Security note:** carrier credentials are operator-class secrets. This page DISPLAYS
connection state — it never holds, transmits, or rotates secrets in plaintext.

---

## APIs

| Endpoint | Purpose | Note |
|----------|---------|------|
| `GET /api/v1/carriers` | List connected accounts (no secret material) | NEW or extend existing |
| `POST /api/v1/carriers/{id}/test` | Synthetic probe (no writes to carrier) | NEW |
| `GET /api/v1/carriers/{id}/webhooks` | Webhook receiver health | NEW |
| `GET /api/v1/carriers/{id}/services` | Supported services | NEW |
| `GET /api/v1/carriers/audit` | Audit log entries (read-only) | NEW |

**NOT exposed to this page:** credential rotation, OAuth start, disconnect.
Those live in admin-v2 (Sprint 11) behind operator-role guard.

`security-permissions` agent MUST verify zero secret material in responses.

---

## Page Structure

- PageHeader (h1: "Carriers", subtitle: "Integration health")
- Tab strip: Carrier Accounts | API Integration | Webhooks | Active Sessions | Audit Log
- Carrier Accounts tab: card grid per carrier (state Badge, success%, latency, calls 24h)
- API Integration tab: endpoint registry (read-only)
- Webhooks tab: receiver health per carrier
- Audit Log tab: scrollable CompactTable (timestamp, actor, action, carrier)
- SessionBanner for auth/network

---

## Mandatory Agents

Same 15-agent base. Adds:
- `security-permissions` — verdict on every response: zero secret material leaked
- `security-write-action-reviewer` — verdict on "Test connection" Btn (must be no-op write)

---

## Acceptance Criteria

1. Page loads, no console errors
2. All 5 tabs render correctly with `data-testid`
3. "Test connection" probe returns latency without modifying carrier state
4. **Zero secrets in any response** (security-permissions verdict explicit)
5. Audit log paginates correctly
6. SessionBanner on auth/permission errors
7. Rollback: remove file

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 16 — Carriers V2
Branch: atlas-v2/sprint-16-carriers-v2 (from origin/main; Sprint 02 merged)

STACK CONSTRAINTS: same as Sprint 14.
Design ref: git show origin/atlas-v2/source-bundle:design-files/carriers-page.jsx

TASK: Create service/app/static/carriers-v2.html — carrier integration registry display.

AUTHORITY:
OWNS: connection state display, webhook health, audit log read, synthetic probe
NEVER: credential storage, OAuth secret handling, carrier disconnection,
       credential rotation (all live in admin-v2 + backend secret store)

SECURITY (mandatory):
- security-permissions verdict: zero secret material in any response
- security-write-action-reviewer verdict: "Test connection" must be no-op write (probe only)
- ZERO credentials, tokens, or OAuth secrets visible in DOM or network responses

BACKEND: read-only endpoints + synthetic-probe POST. No credential APIs on this page.

GATE 2 + 15-agent sequence + test baseline: same as Sprint 14.

End with /deploy after merge.
```
