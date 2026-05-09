/**
 * autofill_pz_select_v3.js — wFirma PZ autofill (FINAL stable version)
 * =====================================================================
 * Reads a PZ_BATCH UI payload (built by service/app/tools/build_pz_batch.py)
 * and fills ONE PZ document, ONE row at a time. Never clicks Save.
 *
 *   1 AWB / 1 SAD  →  1 PZ  →  1 truth
 *
 * Lessons baked in (each one cost a real production failure to discover —
 * read the comments before "fixing"):
 *
 *   L1 — TYPING ≠ SELECTING
 *        Setting input.value never binds the good. wFirma requires the
 *        select event from jQuery UI's autocomplete widget. We trigger it
 *        on the matched DATA item, not via DOM-clicking the <li>.
 *
 *   L2 — SUBSTRING MATCH IS DANGEROUS
 *        "EJL/26-27/015-1" substrings into "EJL/26-27/015-10". DOM-clicking
 *        a substring-matched <li> can attach to the wrong row's data even
 *        when the visible item looks right. We pick by EXACT prefix on the
 *        autocomplete RESPONSE data: label.startsWith(code + " ").
 *
 *   L3 — DOM INDEX ≠ FORM INDEX
 *        wFirma's row identifier is the [N] in
 *        name="data[WarehouseDocumentContent][N][...]". After delete this
 *        does NOT compact. Always parse the form index from the input's
 *        name attribute. Never use Array.indexOf in DOM order.
 *
 *   L4 — SCOPE TO THE TOP DIALOG
 *        wFirma's UI sometimes leaves a stale modal underneath. We tag the
 *        top-most visible dialog by id and scope ALL queries to it.
 *
 *   L5 — AUTO-RECALC MAY REVERT QTY
 *        After binding the good and price, wFirma can recalculate qty back
 *        to 1. We re-confirm qty AFTER everything settles.
 *
 * Usage in browser DevTools Console:
 *
 *   1. Open wFirma → Magazyn → Dokumenty → Dodaj → Dokument PZ
 *   2. Pick supplier (ESTRELLA JEWELS LLP.) manually so the form opens
 *   3. Paste this whole file
 *   4. Paste the payload as a JS literal:
 *        const PAYLOAD = { ... contents of PZ_BATCH_<awb>_ui.json ... };
 *   5. Run:  await fillSinglePZ(PAYLOAD);
 *   6. Review the form visually
 *   7. Click Zapisz manually  (the script will NOT click it)
 *
 * Public API:
 *   await fillSinglePZ(payload)
 *   await selectProductExact(input, code)
 *   markTopDialog()  → returns the scoped element
 */
(function () {
  'use strict';

  // ── Logging ────────────────────────────────────────────────────────────────
  const log  = (...a) => console.log('[PZv3]', ...a);
  const warn = (...a) => console.warn('[PZv3]', ...a);

  // ── Helpers ────────────────────────────────────────────────────────────────

  function setVal(el, v) {
    if (!el) throw new Error('setVal: element is null');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')
          .set.call(el, String(v));
    el.dispatchEvent(new Event('input',  { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('blur',   { bubbles: true }));
  }

  const wait = ms => new Promise(r => setTimeout(r, ms));

  /**
   * L4 — Mark the top-most visible dialog. All other helpers query within
   * this scope only, so a stale background modal can't poison selectors.
   */
  function markTopDialog() {
    const candidates = Array.from(document.querySelectorAll(
      '.ui-dialog, .dialog, .modal, [role="dialog"]'
    )).filter(d => d.offsetParent !== null);
    if (candidates.length === 0) return null;
    const ranked = candidates.map(d => ({
      el: d,
      z: parseInt(getComputedStyle(d).zIndex || '0', 10) || 0,
    })).sort((a, b) => b.z - a.z);
    const top = ranked[0].el;
    top.dataset.pzTop = '1';
    return top;
  }

  function getTop() {
    const tagged = document.querySelector('[data-pz-top="1"]');
    if (tagged && tagged.offsetParent !== null) return tagged;
    return markTopDialog();
  }

  /** L3 — read the form index from the input's name attribute. */
  function formIndex(input) {
    const m = (input && input.name || '').match(/WarehouseDocumentContent\]\[(\d+)\]/);
    return m ? m[1] : null;
  }

  // ── L1 + L2 — exact-prefix product selection via response data ────────────

  /**
   * Fire a jQuery UI autocomplete search and capture the response data.
   * Returns the array of items wFirma returned for the query (NOT the DOM).
   */
  async function searchAndCapture(input, query, timeoutMs = 3000) {
    const $ = window.jQuery;
    const inst = $(input).autocomplete('instance');
    if (!inst) throw new Error('selectProductExact: input is not a jQuery UI autocomplete');

    let captured = null;
    const orig = inst.options.response;
    inst.options.response = function (e, ui) {
      captured = ui.content || [];
      if (orig) return orig.apply(this, arguments);
    };

    input.focus();
    setVal(input, '');
    $(input).autocomplete('search', query);

    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline && captured === null) await wait(50);

    inst.options.response = orig;
    return captured;
  }

  /**
   * L2 — find the data item whose label starts with `code + ' '`.
   * Returns the data object, NOT a DOM element. Throws on no exact match.
   */
  function pickExact(items, code) {
    if (!items) throw new Error(`autocomplete returned no response (offline? blocked?)`);
    const exact = items.find(x => (x.label || '').startsWith(code + ' '));
    if (!exact) {
      const labels = items.map(x => (x.label || '').slice(0, 80));
      throw new Error(
        `Product "${code}" not found by exact prefix. ` +
        `Got ${items.length} candidates; first labels: ${JSON.stringify(labels.slice(0, 3))}`
      );
    }
    return exact;
  }

  /**
   * L1 — trigger jQuery UI's `select` event with the data item directly.
   * This is what wFirma's select handler reads to set the hidden good_id,
   * pull the price, and update the line. Bypasses DOM clicking entirely.
   */
  async function selectProductExact(input, code) {
    const $ = window.jQuery;
    log(`Selecting ${code}`);
    const items = await searchAndCapture(input, code);
    const exact = pickExact(items, code);
    const inst = $(input).autocomplete('instance');
    inst._trigger('select', null, { item: exact });
    $(input).autocomplete('close');
    await wait(300);

    // Verify
    const fi = formIndex(input);
    const top = getTop();
    const goodIdEl = (top || document).querySelector(
      `input[name="data[WarehouseDocumentContent][${fi}][good_id]"]`
    );
    const goodId = goodIdEl?.value || '';
    if (!goodId || goodId === '0') {
      throw new Error(
        `Product "${code}" appeared selected but good_id was not bound ` +
        `(form index ${fi}). Refusing to continue.`
      );
    }
    log(`  ✓ ${code} → good_id=${goodId} (fi=${fi})`);
    return { code, formIndex: fi, goodId, item: exact };
  }

  // ── Row addition + qty/price set ─────────────────────────────────────────

  function findNewRowButton(top) {
    return Array.from(top.querySelectorAll('a, button'))
                .find(el => /nowy wiersz/i.test(el.textContent || ''));
  }

  async function addEmptyRow(top) {
    const btn = findNewRowButton(top);
    if (!btn) throw new Error('"+ Nowy wiersz" button not found in dialog');
    const before = top.querySelectorAll('input.input-name').length;
    window.jQuery(btn).trigger('click');
    const deadline = Date.now() + 3000;
    while (Date.now() < deadline) {
      if (top.querySelectorAll('input.input-name').length > before) return;
      await wait(80);
    }
    throw new Error('new row did not appear within 3s after clicking "Nowy wiersz"');
  }

  function lastInput(top) {
    const all = top.querySelectorAll('input.input-name');
    return all[all.length - 1];
  }

  async function setQty(top, fi, qty) {
    const el = top.querySelector(
      `input[name="data[WarehouseDocumentContent][${fi}][count]"]`
    );
    if (!el) throw new Error(`qty input not found for fi=${fi}`);
    setVal(el, qty);
    el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
    return el;
  }

  async function setPrice(top, fi, price) {
    const el = top.querySelector(
      `input[name="data[WarehouseDocumentContent][${fi}][price]"]`
    );
    if (!el) return null;   // price often auto-fills from good's default — skip if not present
    setVal(el, price);
    el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
    return el;
  }

  // ── Public: fillSinglePZ ──────────────────────────────────────────────────

  /**
   * Fill one PZ document from a UI payload (built by build_pz_batch.py).
   * Payload shape:
   *   {
   *     awb: "...",
   *     lines: [
   *       { product_code, wfirma_good_id, name, qty, price_net_pln, invoice_no },
   *       ...
   *     ]
   *   }
   *
   * Behaviour:
   *   - Assumes the PZ form dialog is already open and supplier is selected.
   *   - First row reuses the dialog's initial empty row; rows 2..N add via
   *     "+ Nowy wiersz".
   *   - For each row: selectProductExact → setQty → (optional setPrice).
   *   - L5: re-confirms qty after all rows are filled.
   *   - Stops fast on any failure. Never silently continues.
   *   - NEVER clicks Save. The operator clicks Zapisz manually.
   *
   * Returns a per-line result table.
   */
  async function fillSinglePZ(payload) {
    if (!window.jQuery) throw new Error('jQuery not on page');
    if (!payload || !Array.isArray(payload.lines) || payload.lines.length === 0) {
      throw new Error('fillSinglePZ: payload.lines must be a non-empty array');
    }

    const top = markTopDialog();
    if (!top) throw new Error('No visible PZ dialog found. Open Dodaj → Dokument PZ first.');

    const results = [];
    log(`Filling ${payload.lines.length} lines for AWB ${payload.awb || '(no awb)'}`);

    for (let i = 0; i < payload.lines.length; i++) {
      const ln = payload.lines[i];
      if (!ln.product_code) throw new Error(`Line ${i + 1}: product_code missing`);
      if (i > 0) await addEmptyRow(top);

      const input = lastInput(top);
      const out = await selectProductExact(input, ln.product_code);

      if (ln.qty != null) {
        await setQty(top, out.formIndex, ln.qty);
      }
      if (ln.price_net_pln != null) {
        await setPrice(top, out.formIndex, ln.price_net_pln);
      }

      // L5 — guard against auto-recalc reverting qty
      await wait(200);
      const qtyEl = top.querySelector(
        `input[name="data[WarehouseDocumentContent][${out.formIndex}][count]"]`
      );
      if (qtyEl && ln.qty != null && qtyEl.value !== String(ln.qty)) {
        warn(`auto-recalc reverted qty on fi=${out.formIndex}; re-applying ${ln.qty}`);
        setVal(qtyEl, ln.qty);
        qtyEl.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
      }

      // Cross-check expected good_id when payload provides one
      if (ln.wfirma_good_id && out.goodId !== String(ln.wfirma_good_id)) {
        throw new Error(
          `Line ${i + 1} (${ln.product_code}): bound good_id ${out.goodId} ` +
          `but payload expected ${ln.wfirma_good_id}. ABORTING.`
        );
      }

      results.push({
        line: i + 1,
        code: ln.product_code,
        fi: out.formIndex,
        good_id: out.goodId,
        qty: qtyEl?.value || null,
      });
    }

    // L5 — final pass: re-confirm every qty value
    await wait(300);
    for (const r of results) {
      const expected = payload.lines[r.line - 1].qty;
      if (expected == null) continue;
      const el = top.querySelector(
        `input[name="data[WarehouseDocumentContent][${r.fi}][count]"]`
      );
      if (el && el.value !== String(expected)) {
        warn(`re-applying qty on fi=${r.fi}: ${el.value} → ${expected}`);
        setVal(el, expected);
        el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
        r.qty = el.value;
      }
    }

    log('All rows filled. Click Zapisz manually after visual review.');
    console.table(results);
    return results;
  }

  // ── Expose ────────────────────────────────────────────────────────────────
  window.fillSinglePZ        = fillSinglePZ;
  window.selectProductExact  = selectProductExact;
  window.markTopDialog       = markTopDialog;
  window.PZ_AUTOFILL_VERSION = '3.0.0';

  log(`autofill_pz_select_v3 loaded (v${window.PZ_AUTOFILL_VERSION})`);
  log('  exposed: fillSinglePZ(payload) · selectProductExact(input, code) · markTopDialog()');
})();
