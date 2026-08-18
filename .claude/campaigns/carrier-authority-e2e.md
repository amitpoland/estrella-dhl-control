# Carrier authority e2e campaign

Status: REVIEW — candidate freeze pending tests + PR
Worktree: `C:\PZ-wt\carrier-authority-e2e`
Branch: `campaign/carrier-authority-e2e`

## Root cause (Track `is_migrated=False`)

Class: **STALE_SETTINGS_INSTANCE + HELPER_ORDERING_DEFECT**
Also true for PZService: **SERVICE_RESTART_REQUIRED**

`migrated_identity_keys()` bound `from app.core.config import settings` at import.
Helpers wrote `CARRIER_CREDENTIAL_MIGRATED=dhl/production/track` then replaced
`config.settings = Settings()`; `is_migrated()` still read the old object.

Fix: read `cfg.settings.carrier_credential_migrated` on the live singleton.

## Production Track/Ship migration

Code + unit tests prove parser, singleton, no dual-truth, rollback of identity
list, UPS block, FedEx adapter.

**Runtime Track rollback/restore and Ship DPAPI write** require Administrator
(store ACL + `nssm restart`). This session cannot elevate. Recorded as
EXTERNAL BLOCKER — operator script after external verification, not before
merge/deploy.

PHASE_0 remains CLOSED. Narrow DHL allowlist unchanged. No AWB. No FedEx
production booking. No UPS booking. No wFirma/inventory/customs writes.

## Authority map

Carrier Master → credential service → DPAPI → `resolve_carrier_credentials`
→ factory (`DHLAdapter` | `FedExSandboxAdapter` | UPS block) →
`CarrierCoordinator` → `carrier_shipments` → `tracking_service` (`_call_fedex`
is the only FedEx HTTP track path).
