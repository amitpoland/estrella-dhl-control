# Agent reconciliation — Carrier Recovery (2026-08-16)

Tree: `C:\PZ-main` @ `9507026a`. Agents were READ-ONLY.

## Consensus (accepted)

1. **No reusable app vault** — secrets = Settings/`.env` only; `C:\PZ-secrets` = deploy-auth HMAC.
2. **Split authority is the root defect** — `carriers_config` non-secret vs `.env` auth.
3. **Single-authority pins** (do not fork):
   - `factory.py`, `coordinator.py`, `shipment_db.py`, `routes_carrier_actions.py`
   - `client_carrier_accounts_db.py`, `dhl_account_resolver.py` (generalize in place)
   - `tracking_service.py` + `tracking_db.py` + `event_processor.py`
   - `carriers-page.jsx`, `AwbGenerateModal` (one booking UX)
4. **Secret store minimum:** DPAPI machine-scope files under `C:\PZ-secrets\carriers\{carrier}\{env}\{capability}` + A→B active pointer.
5. **RBAC:** new `carriers.credentials.write` (admin only). Do **not** use `carriers.edit`.
6. **FedEx:** TRACK today via `_call_fedex` only; live SHIP = future adapter; RATE/RETURN not on ABC — do not dual-implement Track.
7. **UI:** normalize **DHL | FedEx | UPS | Other** inside existing modals; no `AwbFedexModal`/`AwbUpsModal`.

## Conflicts resolved against code/ADRs

| Topic | Resolution |
|---|---|
| ADR-001 5-method Protocol vs 2-method ABC | **Code wins for now.** Extend ABC only when a capability is productized; RATE requires ADR amend before Protocol promotion. |
| Where Track lives for FedEx | Keep **`tracking_service`** as Atlas track authority; adapter `get_shipment` for FedEx only if `_call_fedex` becomes a thin delegate — never two live clients. |
| Storage for ciphertext | Prefer **DPAPI files under `C:\PZ-secrets\carriers\`** over Fernet+key-in-env (Agent 2). Refs/metadata in separate SQLite under carrier storage root — never `master_data.sqlite`. |
| Account resolver name | Generalize **`dhl_account_resolver.py` in place** (Agent 1); do not add `carrier_account_resolver.py` as a second module. |

## Phase 0 (unchanged)

```
PHASE_0 = EXECUTION_BLOCKED
DHL_EXPRESS_API_KEY|SECRET|ALLOWLIST present=false
```

## Agent sources

| Agent | ID |
|---|---|
| Authority Audit | `17863089-db0d-41e4-93ac-1f723505860b` |
| Credential Security | `17683cbf-9bb4-4b7c-a0d1-48b0a33d37ed` |
| FedEx Fit + UI | `dc3a4be9-330a-464b-921b-8704ef0cbecc` |

UI/tracking checklist: `carrier-ui-tracking-convergence.md`
