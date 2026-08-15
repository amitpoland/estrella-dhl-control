# Campaign: Carrier Recovery and Convergence

**Status:** ACTIVE  
**Started:** 2026-08-16  
**Workspace:** `C:\PZ-main`  
**Owner:** Carrier Master → credential resolver → CarrierCoordinator

## Revisions (W0)

| Surface | Value | Carrier-relevant? |
|---|---|---|
| `C:\PZ-main` HEAD | `9507026a` | No delta vs prod in carrier paths |
| `origin/main` | `9507026a` | — |
| Production `version.txt` | `b7f24977…` | Runtime bytes |
| `C:\PZ-verify` | out of path | Unrelated |

`git log b7f24977..HEAD -- <carrier paths>` = **empty**. Deploy delta for Releases B+ is unrelated insurance-export only until carrier PRs land.

## Workstreams

| ID | Name | Status |
|---|---|---|
| W0 | Revision + authority reconciliation | DONE |
| W1 | DHL Phase 0 live restoration | **EXECUTION_BLOCKED** (session: no recheck loop) |
| W2 | Credential/security architecture | **DONE (design + scaffold)** — agents reconciled |
| W3 | Carrier Master credential authority | **IN PROGRESS** — resolver + Memory store + RBAC verbs; DPAPI file store + write APIs next (security-review) |
| W4 | DHL migrate to resolver | Depends W3 write path + Phase 0 CLOSE |
| W5 | Canonical carrier selection/resolution | Design reconciled; impl after W3 |
| W6 | FedEx sandbox adapter | Depends W1 CLOSED + W3/W4 |
| W7 | Tracking convergence | Design reconciled (keep `tracking_service` authority) |
| W8 | UI convergence | Design reconciled (normalize enums in existing modals) |
| W9 | Regression/security validation | Scaffold tests green (`test_carrier_credential_authority.py`) |
| W10 | Deploy slices A→E | After validation |

## W1 — Phase 0 (session lock)

Presence check 2026-08-16 (once this session):

```
DHL_EXPRESS_API_KEY      present=false
DHL_EXPRESS_API_SECRET   present=false
CARRIER_LIVE_ALLOWLIST   present=false
CARRIER_API_STATUS       live
DHL_TRACKING_API_STATUS  active
```

**PHASE_0 = EXECUTION_BLOCKED**  
**reason = missing operator-controlled production configuration**

Do not recheck repeatedly in this session. Resume only on operator signal:  
`Express creds + allowlist inserted. Allowlist is narrow|wildcard`

Temporary bridge (when unblocked): `.env` restore → prove DHL → retire as routine path in W3/W4.

## Target architecture

```
Carrier Master (control + metadata + refs)
        ↓
secure secret authority (ciphertext only)
        ↓
resolve_carrier_credentials(carrier, capability, environment)
resolve_carrier_capability(carrier, capability, environment)
        ↓
factory → DHLAdapter | FedExAdapter | UPSAdapter
        ↓
CarrierCoordinator
        ↓
carrier_shipments + labels + Atlas tracking
```

## Release slices

| Release | Content |
|---|---|
| A | Phase 0 `.env` Express + allowlist (ops) |
| B | Secure store + resolver + DHL migrate |
| C | Selector/coordinator convergence |
| D | FedEx sandbox |
| E | FedEx production (external cert gate) |

## Done when

ONE Carrier Master · ONE credential authority · ONE resolver · ONE coordinator · ONE booking UX · ONE shipment store · ONE tracking authority · DHL restored · FedEx on same path · UPS plug-in without redesign · no routine `.env` for carrier secrets.
