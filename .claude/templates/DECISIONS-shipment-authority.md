### <DATE> — Shipment Detail canonical authority declared (slice-01)
DECISION: service/app/static/v2/shipment-detail-page.jsx is the sole canonical
authority for the Shipment Detail module.
BASIS: Authority census 2026-07-01T015910Z @ aa414d90.
  - Loaded at v2/index.html:299 — only the base .jsx is in the script list.
  - shipment-detail-page.v1.jsx and .v2.jsx are on disk, not loaded, and each
    (re)defines ShipmentDetailPage — a latent window-global override collision.
  (01-frontend-authority-map.md:23; 06-evidence-backfill.md §Claim 2, §4c)
CONSEQUENCE: the two dead versioned JSX files are retired and DELETED in this slice
  (C:\PZ-verify only; not committed, not deployed).
  Reversal: git checkout HEAD -- service/app/static/v2/shipment-detail-page.v1.jsx service/app/static/v2/shipment-detail-page.v2.jsx
  Pre-delete blob SHAs: v1=<SHA-v1>  v2=<SHA-v2>
SCOPE: this DECISION does NOT resolve the /dashboard/shipment-detail.html V1
  direct-link surface (decision D-3, still open). Only the two dead .v?.jsx files.
