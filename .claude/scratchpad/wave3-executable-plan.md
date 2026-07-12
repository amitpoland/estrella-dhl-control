# Wave 3 — Shipment Detail: SAD + Documents (executable plan)

Branch: feat/v2-wave3-sad-documents (base origin/main @ 95636921). One cohesive PR.
Operator decisions (locked 2026-07-13): (1) FULL inline route + identity contract;
(2) canonical delete-by-id + fix orphan + non-deletable guard + audited replace;
(3) SAD upload + role-gated parse/recheck + verify read.

## Slice 3-1 — Backend document-identity contract (manifest)
File: service/app/api/routes_upload.py (GET /upload/shipment/{id}/documents :1208)
- Emit per row: document_id(=id), document_type, authority(=source), original_filename(=file_name),
  mime_type (infer from ext), created_at, is_current, can_view/can_download/can_replace/can_delete,
  view_url, download_url.
- REMOVE file_path (absolute-path leak) + any other internal path from the response.
- Capability rules: generated fiscal/customs (pz_pdf,pz_xlsx,audit_memo,sad_pdf,sad_xml) → can_delete=false;
  can_replace true only for sad_pdf (existing replace route) initially; can_view/download from serving route.
- view_url → inline serving; download_url → attachment serving.

## Slice 3-2 — Inline serving
File: routes_pz.py file routes (/files/{batch}/{name}, /files/{batch}/source/{cat}/{name})
- Add ?disposition=inline → Content-Disposition: inline (browser-safe PDF view). Default stays attachment.
- Keep Cache-Control: no-store. media_type by ext.

## Slice 3-3 — Canonical delete-by-id + schema supersede
- Schema: add is_current INTEGER DEFAULT 1 (+ superseded_by TEXT DEFAULT '') to shipment_documents (migration).
- DELETE /api/v1/upload/shipment/{batch_id}/documents/{document_id} on documents.db authority:
  remove shipment_documents row + linked lines (packing.db packing_lines/documents by hash; documents.db
  sales_packing_lines by sales_document_id) + disk file + audit timeline event. require_api_key + X-Operator.
  Non-deletable guard (409) for generated fiscal/customs types. Confirmation is UI-side.
- Replace (SAD + general): mark old row is_current=0/superseded_by=new_id instead of silent overwrite; audit event.

## Slice 3-4 — pz-api.js wrappers
getShipmentDocuments(batchId), uploadSad(batchId,file), recheckSad(batchId) (POST /dashboard/batches/{id}/recheck {mode:'sad'}),
deleteDocument(batchId,docId), replaceDocument(batchId,docId,file), getDhlClearanceStatus(batchId).

## Slice 3-5 — shipment-detail-page.jsx DocumentsTab + SAD
- Repoint DocumentsTab to getShipmentDocuments manifest; drop _WIREFRAME_DOC_CARDS mismap.
- Render real rows grouped by document_type/authority; View(inline) vs Download(attachment); Upload/Replace/Delete
  gated by capability flags; purchase≠sales packing distinct.
- SAD card: real upload (uploadSad) + role-gated recheck (recheckSad) + surface agency_sad_decision +
  sad_invoice_authority + PZ-gate reason; remove "use V1".
- DHL tab: surface read-only clearance-status/readiness; keep correspondence writes on Console (do NOT wire).

## Tests
- manifest contract test (identity fields present, file_path absent, capability flags correct per type).
- inline disposition test (?disposition=inline → inline header).
- delete-by-id test: deletes registry+lines+disk+audit; non-deletable generated/customs → 409; orphan-fix (row gone).
- replace supersede test (old is_current=0).
- golden 160/160, smoke 63, Babel, PII scan.

## Reviews: backend-safety + security (delete/upload/path-leak) + reviewer-challenge + frontend-flow.
## Safety: customs SAD parser/decision preserved; generated fiscal/customs non-deletable; no packing value mutation.
