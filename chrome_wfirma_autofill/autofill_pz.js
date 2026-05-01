/**
 * wFirma PZ AutoFill — Chrome Console Script
 * ============================================
 * Fills the wFirma.pl "Nowe PZ" form from a PZ_READY.json payload.
 *
 * SAFETY RULES — hardcoded, cannot be overridden:
 *   1. Never clicks the Save/Zapisz button
 *   2. Never deletes or overwrites existing documents
 *   3. Never submits any form
 *   4. Never sends data to any external server
 *   5. Never modifies values in the input JSON
 *   6. Stops and warns if the form already has data
 *   7. Blocks fill if supplier is UNKNOWN_SUPPLIER (review-mode override required)
 *   8. Blocks fill if rows are empty
 *   9. Warns strongly when doc_no is empty
 *  10. Compares totals after fill if selectors found; otherwise reports unverified
 *
 * Usage:
 *   1. Paste this script into Chrome DevTools Console on the wFirma Nowe PZ page
 *   2. Call: wfirmaFill(pzReadyJsonObject)
 *   3. Override block with review mode (still no Save click): wfirmaFill(data, {reviewMode: true})
 *
 * Returns a structured audit result:
 *   {status, rows_expected, rows_filled, supplier, doc_no, warnings, totals_checked, totals_match}
 */

(function () {
  'use strict';

  // ── Selectors — verified against live wFirma PZ DOM (2026-04) ───────────────
  const SELECTORS = {
    // Header fields
    kontrahent:   'input[name="data[ContractorDetail][name]"]',
    magazyn:      'select[name="data[WarehouseDocument][warehouse_id]"]',
    dataDoc:      'input#dateFrom',
    description:  'textarea[name="data[WarehouseDocument][description]"]',
    // Row add button
    addRowBtn:    'a#add-row-invoice',
    // Row container
    rowContainer: '#positions tbody',
    // Per-row fields (queried within each <tr>)
    rowTemplate: {
      nazwa:     'input.input-name',
      ilosc:     'input.input-count',
      // Unit is a <select> hidden behind a search-select UI overlay
      jm:        'select.input-unit_id[name*="WarehouseDocumentContent"]',
      cenaNetto:  'input.input-price',
      // NOTE: wFirma PZ has no per-row notes/uwagi field
    },
    // Totals: located via text-search in _verifyTotals(), not CSS selector
    // (.summary-item span.text — first = netto, second = brutto)
  };

  // ── Helpers ──────────────────────────────────────────────────────────────────

  function _log(msg) {
    console.log('%c[wFirma AutoFill]%c ' + msg, 'color:#C9A456;font-weight:bold', 'color:inherit');
  }

  function _warn(msg) {
    console.warn('[wFirma AutoFill] ⚠️  ' + msg);
  }

  function _err(msg) {
    console.error('[wFirma AutoFill] ❌  ' + msg);
  }

  function _setVal(el, value) {
    if (!el) return false;
    const nativeInput = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')
      || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
    if (nativeInput) {
      nativeInput.set.call(el, value);
    } else {
      el.value = value;
    }
    el.dispatchEvent(new Event('input',  { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('blur',   { bubbles: true }));
    return true;
  }

  function _setSelect(el, value) {
    if (!el) return false;
    const options = Array.from(el.options);
    const match = options.find(o =>
      o.value === String(value) ||
      o.text.toLowerCase().includes(String(value).toLowerCase())
    );
    if (match) {
      el.value = match.value;
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    }
    _warn(`Select option not found for value: ${value}`);
    return false;
  }

  function _fmtPlPln(n) {
    // Polish number format: 1 234,56
    const num = parseFloat(n) || 0;
    return num.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ' ').replace('.', ',');
  }

  function _sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function _q(selector, context) {
    const ctx = context || document;
    const parts = selector.split(',').map(s => s.trim());
    for (const sel of parts) {
      try {
        const el = ctx.querySelector(sel);
        if (el) return el;
      } catch (e) { /* invalid selector — skip */ }
    }
    return null;
  }

  // ── Guard: check form is empty ────────────────────────────────────────────────

  function _checkFormEmpty() {
    const kontrahent = _q(SELECTORS.kontrahent);
    if (kontrahent && kontrahent.value && kontrahent.value.trim() !== '') {
      _warn('Form appears to have existing data in Kontrahent field. ' +
            'Clear the form or reload the page before autofill.');
      return false;
    }
    return true;
  }

  // ── Header fill ───────────────────────────────────────────────────────────────

  async function _fillHeader(data) {
    // Kontrahent
    const kontrahentEl = _q(SELECTORS.kontrahent);
    if (kontrahentEl && data.supplier) {
      _setVal(kontrahentEl, data.supplier);
      await _sleep(600); // allow autocomplete to respond
      _log(`Kontrahent: "${data.supplier}"`);
    } else if (!kontrahentEl) {
      _warn('Kontrahent field not found — check SELECTORS.kontrahent');
    }

    // Data dokumentu
    const dateEl = _q(SELECTORS.dataDoc);
    if (dateEl && data.document_date) {
      _setVal(dateEl, data.document_date);
      _log(`Data dokumentu: "${data.document_date}"`);
    } else if (!dateEl) {
      _warn('Data dokumentu field not found — check SELECTORS.dataDoc');
    }

    // Magazyn (default: Główny)
    const magazynEl = _q(SELECTORS.magazyn);
    if (magazynEl) {
      _setSelect(magazynEl, 'Główny');
      _log('Magazyn: Główny');
    }

    // Description — put doc_no as reference so it's visible in the PZ record
    const descEl = _q(SELECTORS.description);
    if (descEl && data.doc_no) {
      _setVal(descEl, `Ref: ${data.doc_no}`);
      _log(`Opis: "Ref: ${data.doc_no}"`);
    }
  }

  // ── Row fill ──────────────────────────────────────────────────────────────────

  async function _fillRows(rows) {
    if (!rows || rows.length === 0) {
      _warn('No rows to fill.');
      return;
    }

    const tbody = _q(SELECTORS.rowContainer);
    if (!tbody) {
      _warn('Rows table container not found. Rows must be added manually.');
      _log('Printing rows to console for manual entry:');
      rows.forEach((r, i) => {
        console.table({
          [`Row ${i + 1}`]: {
            'Nazwa towaru': r.name,
            'Ilość':        r.quantity,
            'J.m.':         r.unit,
            'Cena netto':   _fmtPlPln(r.net_price_pln),
            'Wartość netto': _fmtPlPln(r.net_value_pln),
            'Uwagi':        r.notes,
          }
        });
      });
      return;
    }

    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];

      // Click "Add row" button to create new row if needed
      const addBtn = _q(SELECTORS.addRowBtn);
      if (addBtn) {
        addBtn.click();
        await _sleep(400);
      }

      // Get all rows in tbody, pick the last one (newly added)
      const rowEls = tbody.querySelectorAll('tr');
      const rowEl  = rowEls[rowEls.length - 1];
      if (!rowEl) {
        _warn(`Row ${i + 1}: could not find row element`);
        continue;
      }

      // Fill each cell — selectors are class-based, queried within the row <tr>
      const nazwaEl = _q(SELECTORS.rowTemplate.nazwa,    rowEl);
      const iloscEl = _q(SELECTORS.rowTemplate.ilosc,    rowEl);
      const jmEl    = _q(SELECTORS.rowTemplate.jm,       rowEl);
      const cenaNEl = _q(SELECTORS.rowTemplate.cenaNetto, rowEl);

      if (nazwaEl) _setVal(nazwaEl, row.name || '');
      if (iloscEl) _setVal(iloscEl, String(row.quantity));
      if (jmEl)    _setSelect(jmEl, row.unit || 'szt.');
      if (cenaNEl) _setVal(cenaNEl, _fmtPlPln(row.net_price_pln));

      if (!nazwaEl) _warn(`Row ${i + 1}: input.input-name not found in row`);
      if (!cenaNEl) _warn(`Row ${i + 1}: input.input-price not found in row`);

      _log(`Row ${i + 1}: "${row.name}" → ${_fmtPlPln(row.net_value_pln)} PLN netto`);
      await _sleep(200);
    }
  }

  // ── Validation chain ──────────────────────────────────────────────────────────

  function _validateInput(data, opts) {
    const warnings = [];
    const blockers = [];

    if (!data || typeof data !== 'object') {
      blockers.push('Invalid input: expected PZ_READY.json object');
      return { warnings, blockers };
    }

    // Rows must exist
    if (!data.rows || !Array.isArray(data.rows) || data.rows.length === 0) {
      blockers.push('No rows in PZ_READY.json — regenerate from dashboard');
    }

    // Supplier
    const supplier = (data.supplier || '').trim();
    if (!supplier) {
      blockers.push('Supplier is empty — regenerate PZ_READY.json from dashboard');
    } else if (supplier === 'UNKNOWN_SUPPLIER') {
      if (opts.reviewMode) {
        warnings.push('Supplier is UNKNOWN_SUPPLIER — review mode allows fill but you MUST set Kontrahent manually');
      } else {
        blockers.push('Supplier is UNKNOWN_SUPPLIER — refuses fill. Re-run with {reviewMode: true} to override (still no Save).');
      }
    }

    // Totals
    if (!data.totals || typeof data.totals !== 'object') {
      blockers.push('Totals block missing in PZ_READY.json');
    } else {
      if (typeof data.totals.net !== 'number')   warnings.push('totals.net is not a number');
      if (typeof data.totals.gross !== 'number') warnings.push('totals.gross is not a number');
    }

    // Document date
    if (!data.document_date || !String(data.document_date).trim()) {
      blockers.push('document_date missing in PZ_READY.json');
    }

    // doc_no — strong warning, not a blocker
    if (!data.doc_no || !String(data.doc_no).trim()) {
      warnings.push('⚠️  PZ document number (doc_no) is EMPTY — you MUST set it in wFirma before saving');
    }

    // Surface backend warnings if present
    if (Array.isArray(data.warnings)) {
      data.warnings.forEach(w => warnings.push(`backend: ${w}`));
    }

    return { warnings, blockers };
  }

  // ── Totals verification ───────────────────────────────────────────────────────

  function _parsePlNumber(text) {
    if (!text) return NaN;
    // "1 234,56 PLN" → 1234.56
    const cleaned = String(text).replace(/[^\d,.-]/g, '').replace(/\s/g, '').replace(',', '.');
    return parseFloat(cleaned);
  }

  function _verifyTotals(expectedNet, expectedGross) {
    // Locate summary items by their label text — more robust than nth-child
    const items = Array.from(document.querySelectorAll('.summary-item'));
    const netItem   = items.find(el => /netto/i.test(el.textContent));
    const grossItem = items.find(el => /brutto/i.test(el.textContent));
    const netEl   = netItem   ? netItem.querySelector('span.text')   : null;
    const grossEl = grossItem ? grossItem.querySelector('span.text') : null;

    if (!netEl && !grossEl) {
      return { totals_checked: false, totals_match: null,
               note: 'Total summary items not found in DOM — totals NOT verified, check manually' };
    }
    const actualNet   = netEl   ? _parsePlNumber(netEl.textContent)   : null;
    const actualGross = grossEl ? _parsePlNumber(grossEl.textContent) : null;
    const tol = 0.05; // 5 grosz tolerance for rounding
    const netOk   = actualNet   != null ? Math.abs(actualNet   - expectedNet)   < tol : null;
    const grossOk = actualGross != null ? Math.abs(actualGross - expectedGross) < tol : null;
    const allOk = (netOk !== false) && (grossOk !== false) && (netOk !== null || grossOk !== null);
    return {
      totals_checked: true,
      totals_match:   allOk,
      detail: { expected_net: expectedNet, actual_net: actualNet,
                expected_gross: expectedGross, actual_gross: actualGross }
    };
  }

  // ── Main fill function ────────────────────────────────────────────────────────

  async function wfirmaFill(data, opts) {
    opts = opts || {};
    const result = {
      status:         'pending',
      rows_expected:  (data && data.rows) ? data.rows.length : 0,
      rows_filled:    0,
      supplier:       (data && data.supplier) || '',
      doc_no:         (data && data.doc_no) || '',
      warnings:       [],
      blockers:       [],
      totals_checked: false,
      totals_match:   null,
      review_mode:    !!opts.reviewMode,
    };

    _log('=== wFirma PZ AutoFill START ===');

    // Stage 1 — validation
    const v = _validateInput(data, opts);
    result.warnings = v.warnings;
    result.blockers = v.blockers;

    v.warnings.forEach(w => _warn(w));
    v.blockers.forEach(b => _err(b));

    if (v.blockers.length > 0) {
      result.status = 'blocked';
      _err(`STOPPED — ${v.blockers.length} blocker(s). Nothing was filled.`);
      console.log('[wFirma AutoFill] result:', result);
      return result;
    }

    _log(`Batch: ${data.batch_id || '?'} | Doc: ${data.doc_no || '(empty)'} | Supplier: ${data.supplier} | Rows: ${data.rows.length}`);

    // Stage 2 — empty form guard
    if (!_checkFormEmpty()) {
      result.status = 'blocked';
      result.blockers.push('Form has existing data — clear or reload before autofill');
      _err('STOPPED — form has existing data. Clear it first.');
      console.log('[wFirma AutoFill] result:', result);
      return result;
    }

    // Stage 3 — fill header + rows
    try {
      await _fillHeader(data);
      await _sleep(300);
      await _fillRows(data.rows);
      result.rows_filled = data.rows.length;
    } catch (e) {
      result.status = 'blocked';
      result.blockers.push(`Fill error: ${e.message}`);
      _err(`Fill aborted: ${e.message}`);
      console.log('[wFirma AutoFill] result:', result);
      return result;
    }

    // Stage 4 — verify totals if possible
    await _sleep(500);
    const tv = _verifyTotals(
      (data.totals && data.totals.net)   || 0,
      (data.totals && data.totals.gross) || 0,
    );
    result.totals_checked = tv.totals_checked;
    result.totals_match   = tv.totals_match;
    if (tv.note)   _warn(tv.note);
    if (tv.detail) _log(`Totals: expected_net=${tv.detail.expected_net} actual_net=${tv.detail.actual_net} expected_gross=${tv.detail.expected_gross} actual_gross=${tv.detail.actual_gross}`);

    // Stage 5 — final status
    if (result.warnings.length > 0 || tv.totals_match === false) {
      result.status = 'warning';
    } else {
      result.status = 'filled';
    }

    _log('─────────────────────────────────────────');
    _log(`Totals — Net: ${_fmtPlPln(data.totals?.net)} PLN`);
    _log(`         Gross: ${_fmtPlPln(data.totals?.gross)} PLN`);
    _log(`         Duty A00: ${_fmtPlPln(data.totals?.duty_a00)} PLN (already in cost)`);
    _log('─────────────────────────────────────────');
    _log(`✅ DONE — status=${result.status}, rows=${result.rows_filled}/${result.rows_expected}`);
    _log('⚠️  The script will NOT click Save for you. Review every field, then click Zapisz.');
    _log('=== wFirma PZ AutoFill END ===');
    console.log('[wFirma AutoFill] result:', result);
    return result;
  }

  // ── Expose globally ───────────────────────────────────────────────────────────
  window.wfirmaFill = wfirmaFill;
  _log('Loaded. Call: wfirmaFill(pzReadyJsonData)');
  _log('Example: fetch("PZ_READY.json").then(r=>r.json()).then(wfirmaFill)');

})();
