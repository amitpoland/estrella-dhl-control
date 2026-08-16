# Design: Carrier credential authority (Phase 1 / Release B)

**Status:** DRAFT — security-review required before write APIs  
**Campaign:** `.claude/campaigns/carrier-recovery-convergence.md`  
**Reconciled:** `.claude/campaigns/carrier-agent-reconciliation-2026-08-16.md`  
**Date:** 2026-08-16

## Problem

Split authority: `carriers_config` (non-secret UI) vs `C:\PZ\.env` (real auth). Production can show live gates while Express KEY/SECRET/ALLOWLIST are absent.

## Finding: no reusable vault

Repo search: no DPAPI/Fernet/keyring/AESGCM credential vault in `service/app`.  
`cryptography` absent from `service/requirements.txt`.  
`C:\PZ-secrets` = deploy signing / gate evidence only.  
Production carrier secrets today = pydantic Settings ← `C:\PZ\.env`.

**Decision:** implement minimum encrypted secret authority owned by Carrier Master control plane. Do not put ciphertext in `master_data.sqlite`.

## Proposed storage (minimum) — Agent 2 accepted

| Layer | Store | Contents |
|---|---|---|
| Control | `carrier_credential_refs` SQLite under carrier storage root (not `master_data.sqlite`) | carrier, environment, capability, active_slot, previous_slot, status, fingerprint/mask, last_validated_at, last_rotated_at, updated_by |
| Secret | DPAPI-sealed files under `C:\PZ-secrets\carriers\{carrier}\{env}\{capability}.{A\|B}` + `{capability}.active` pointer | ciphertext only |
| Master UI | Carrier Master projecting readiness | configured yes/no, masks, timestamps — never raw |

**Encryption (locked for v1):** DPAPI `CryptProtectData` with machine scope so NSSM `PZService` can decrypt without interactive profile. Do **not** introduce Fernet+key-in-`.env` (same failure mode).

## Neutral identity

```
(carrier, environment, capability) → credential_reference
```

Examples: `dhl/production/ship`, `dhl/production/track`, `fedex/sandbox/ship_rate`, `fedex/sandbox/track`.

Multiple capabilities MAY share one reference when the vendor uses the same credential set (e.g. DHL Express ship+ePOD+documents).

## Resolvers

```python
resolve_carrier_credentials(carrier, capability, environment) -> CredentialBundle | raises CARRIER_CREDENTIAL_NOT_CONFIGURED
resolve_carrier_capability(carrier, capability, environment) -> Ready | NotProvisioned | NotConfigured | Disabled | AuthFailed
```

Adapters receive resolved bundles only. Coordinator never sees raw secrets.

## Rotation

A active → store B encrypted → non-chargeable validate B → PASS: activate B, retire A; FAIL: keep A.

No Reveal Secret. GET = masked metadata only.

## RBAC (locked)

| Verb | Recommendation |
|---|---|
| `carriers.credentials.write` | **NEW** — admin-only; required for Add/Replace/Validate/Rotate/Disable |
| `carriers.credentials.view` | Optional — presence/fingerprint/timestamps only |
| `carriers.edit` | **Forbidden** for secret mutation (logistics has it) |
| `master.admin` | Not preferred alone (not carrier-scoped) |

## Allowlist semantics (fix in Release B)

Today: Ship create fail-closed on empty allowlist; ePOD/docs use `or "*"`.  
Converge: allowlist is a **capability policy** for chargeable Ship only; never default `*` in Ship path.

## Migration (DHL first)

1. Implement store + resolver.  
2. Dual-read: resolver prefers Carrier Master ref; fallback Settings once with explicit deprecation flag.  
3. Prove Ship/Track/ePOD/Documents.  
4. Retire Settings fallback for migrated capabilities.  
5. Then FedEx sandbox via same resolver.

## Out of scope here

FedEx booking code, UPS API, production FedEx certification.
