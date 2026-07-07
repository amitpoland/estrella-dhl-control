// use-shipment-documents.jsx — V2 reusable data hook for shipment source documents.
// Exports: window.useShipmentDocuments
//
// Simple, STATELESS hook (no module-level promise cache). One fetch per mount of
//   GET /api/v1/upload/shipment/{batchId}/documents
// (the same read DocumentsRegistry already uses). Read-only; never writes.
// Returns { documents, loading, error }. IIFE-scoped so no globals leak except the
// single window export.
(function () {
  function useShipmentDocuments(batchId) {
    const [documents, setDocuments] = React.useState(null);
    const [loading,   setLoading]   = React.useState(true);
    const [error,     setError]     = React.useState(null);

    React.useEffect(() => {
      let alive = true;
      if (!batchId) { setDocuments([]); setLoading(false); setError(null); return; }
      setLoading(true); setError(null);
      window.EstrellaShared.apiFetch(`/api/v1/upload/shipment/${encodeURIComponent(batchId)}/documents`)
        .then((r) => { if (!alive) return; setDocuments((r && r.documents) || []); setLoading(false); })
        .catch((e) => { if (!alive) return; setError((e && e.message) || 'documents unavailable'); setLoading(false); });
      return () => { alive = false; };
    }, [batchId]);

    return { documents, loading, error };
  }

  window.useShipmentDocuments = useShipmentDocuments;
})();
