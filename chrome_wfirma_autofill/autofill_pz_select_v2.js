/**
 * autofill_pz_select_v2.js — wFirma PZ product-selection helpers
 * ==============================================================
 * Drop-in browser-console script. Fixes the "typing != selecting" bug:
 * setting input.value does NOT bind the product to the line. wFirma
 * requires the user to PICK the autocomplete dropdown item.
 *
 * Exposes 3 functions on window:
 *   waitFor(conditionFn, timeoutMs=2000, intervalMs=100)
 *   selectProduct(inputElement, productCode)
 *   fillPZRow(rowElement, {code, qty, price})
 *
 * Each function fails fast (throws) on missing dropdown, missing item,
 * or unverified selection. Never silently continues.
 *
 * Usage (paste into DevTools Console on wFirma → Magazyn → PZ → Nowe PZ):
 *   1. Paste this whole file.
 *   2. Test: await selectProduct(
 *        document.querySelector('input.input-name, input[name*="name"]'),
 *        'EJL/26-27/015-3'
 *      );
 *   3. Or full row: await fillPZRow(rowElement, {
 *        code: 'EJL/26-27/015-3', qty: 1, price: 70.41
 *      });
 *
 * SAFETY: never clicks Save. Read-only on form structure. No network.
 */
(function () {
  'use strict';

  // ── Config ────────────────────────────────────────────────────────────────
  const DROPDOWN_SELECTORS = [
    '.ui-menu-item',
    '[role="option"]',
    '.autocomplete-suggestion',
    '.ui-autocomplete .ui-menu-item',
    'li.ui-menu-item',
  ];

  const DEFAULT_TIMEOUT_MS  = 2000;
  const DEFAULT_INTERVAL_MS = 100;

  // ── Logging ───────────────────────────────────────────────────────────────
  const log  = (...args) => console.log('[PZ-SELECT]',  ...args);
  const warn = (...args) => console.warn('[PZ-SELECT]', ...args);

  // ── Helpers ───────────────────────────────────────────────────────────────

  /**
   * Poll `conditionFn` every intervalMs ms until it returns truthy or timeout.
   * Returns the truthy value (whatever conditionFn returned). Throws on timeout.
   */
  async function waitFor(conditionFn, timeoutMs = DEFAULT_TIMEOUT_MS,
                         intervalMs = DEFAULT_INTERVAL_MS) {
    const deadline = Date.now() + timeoutMs;
    let last = null;
    while (Date.now() < deadline) {
      try { last = conditionFn(); } catch (e) { last = null; }
      if (last) return last;
      await new Promise(r => setTimeout(r, intervalMs));
    }
    throw new Error(`waitFor: condition not met in ${timeoutMs}ms`);
  }

  /** Set value on an input/select and fire the events wFirma listens to. */
  function setValue(el, value) {
    if (!el) throw new Error('setValue: element is null');
    const tag = (el.tagName || '').toLowerCase();
    const proto = tag === 'select'
      ? window.HTMLSelectElement.prototype
      : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, String(value));
    el.dispatchEvent(new Event('input',  { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  /** Pick the first visible dropdown item whose text contains productCode. */
  function findDropdownItem(productCode) {
    for (const sel of DROPDOWN_SELECTORS) {
      const items = Array.from(document.querySelectorAll(sel));
      // Filter visible (offsetParent truthy)
      const visible = items.filter(el => el.offsetParent !== null);
      // Prefer exact-code match; fall back to substring
      const exact = visible.find(el => (el.textContent || '').trim() === productCode);
      if (exact) return exact;
      const contains = visible.find(el => (el.textContent || '').includes(productCode));
      if (contains) return contains;
    }
    return null;
  }

  /** Try several places where wFirma may stash the bound good_id.
   *  Confirmed live: wFirma uses input[name="data[WarehouseDocumentContent][N][good_id]"]
   *  in the same row. Read THAT first, then fall back to other patterns.
   */
  function readBoundGoodId(inputEl) {
    if (!inputEl) return null;
    const row = inputEl.closest('tr, .row, .form-row, .warehouse-document-content, .position')
              || inputEl.parentElement;
    if (row) {
      // Most reliable selector — confirmed live on wFirma 2026-05-03
      const direct = row.querySelector('input[type="hidden"][name*="[good_id]"]');
      if (direct && direct.value && direct.value !== '0') return direct.value.trim();

      // Fallback selectors
      const fallbacks = [
        'input[type="hidden"][name*="good"][name*="id"]',
        'input[type="hidden"][name*="product"][name*="id"]',
      ];
      for (const sel of fallbacks) {
        const h = row.querySelector(sel);
        if (h && h.value && /^[1-9]\d*$/.test(h.value.trim())) return h.value.trim();
      }
    }
    // Last-resort: data-* attributes on the input itself
    const dataCands = [
      inputEl.dataset && inputEl.dataset.goodId,
      inputEl.dataset && inputEl.dataset.id,
      inputEl.getAttribute('data-good-id'),
      inputEl.getAttribute('data-id'),
    ];
    for (const v of dataCands) {
      if (v && /^[1-9]\d*$/.test(String(v).trim())) return String(v).trim();
    }
    return null;
  }

  // ── Public: selectProduct ────────────────────────────────────────────────

  /**
   * Type a product code into an input, wait for the dropdown, click the
   * matching item, and verify the selection committed.
   *
   * Throws on:
   *   - dropdown not found within timeout
   *   - no item matching productCode
   *   - selection not verified after click
   */
  async function selectProduct(inputElement, productCode) {
    if (!inputElement) throw new Error('selectProduct: inputElement is null');
    if (!productCode)  throw new Error('selectProduct: productCode is empty');
    const $ = window.jQuery || window.$;
    if (!$) throw new Error('selectProduct: jQuery not available on this page');

    log(`Selecting product: ${productCode}`);

    // 1. focus + clear (synthetic input events alone don't trigger jQuery UI
    //    autocomplete — confirmed live against wFirma 2026-05-03)
    inputElement.focus();
    inputElement.dispatchEvent(new Event('focus', { bubbles: true }));
    setValue(inputElement, '');

    // 2. trigger jQuery UI autocomplete's `search` directly. This is the
    //    documented widget API for forcing a query and is what wFirma
    //    actually responds to.
    try {
      $(inputElement).autocomplete('search', productCode);
    } catch (e) {
      throw new Error(`autocomplete('search') failed: ${e.message}. ` +
                      `Is this input the wFirma product field with input.input-name class?`);
    }

    // 3. wait for the dropdown item carrying this code
    let item;
    try {
      item = await waitFor(() => findDropdownItem(productCode), DEFAULT_TIMEOUT_MS);
    } catch (e) {
      throw new Error(`Dropdown not found for "${productCode}" within ${DEFAULT_TIMEOUT_MS}ms. ` +
                      `Common causes: (1) good was created AFTER this dialog opened — close & re-open. ` +
                      `(2) the code is not registered in wFirma — verify via goods/find.`);
    }
    log('Dropdown found:', (item.textContent || '').trim().slice(0, 100));

    // 4. click the item — jQuery UI binds to mousedown on .ui-menu-item.
    //    Use jQuery's trigger so the widget's namespaced handlers fire.
    $(item).trigger('mousedown');
    $(item).trigger('mouseup');
    $(item).trigger('click');

    // 5. verify — the input should now show the product NAME (not the code),
    //    AND a hidden good_id field in the same row should be set
    await new Promise(r => setTimeout(r, 200));   // tiny settle for AJAX-driven side-effects
    const valueAfter = (inputElement.value || '').trim();
    const goodId     = readBoundGoodId(inputElement);

    // The post-click input value is usually the product NAME (not the code),
    // so we accept either: (a) value contains the code, OR (b) goodId is set.
    const ok = valueAfter.includes(productCode) || !!goodId;
    if (!ok) {
      throw new Error(
        `Product selection failed for "${productCode}" ` +
        `(input value="${valueAfter}", bound good_id=${goodId || 'null'})`
      );
    }
    log(`Product selected ✓  good_id=${goodId || '(none — value match)'}, value="${valueAfter}"`);
    return { productCode, goodId, valueAfter };
  }

  // ── Public: fillPZRow ────────────────────────────────────────────────────

  /**
   * Fill one PZ form row with product, qty, price.
   *
   * `rowElement` should be the <tr> (or container) holding the row's inputs.
   * Falls back to document-level lookup if a per-row input isn't found.
   */
  async function fillPZRow(rowElement, data) {
    const { code, qty, price } = data || {};
    if (!code)  throw new Error('fillPZRow: data.code missing');
    if (qty   == null || qty   <= 0) throw new Error('fillPZRow: qty must be > 0');
    if (price == null || price <= 0) throw new Error('fillPZRow: price must be > 0');

    const within = sel => (rowElement && rowElement.querySelector(sel))
                          || document.querySelector(sel);

    const nameInput = within('input.input-name')
                   || within('input[name*="[name]"]')
                   || within('input[name*="name"]');
    if (!nameInput) throw new Error('fillPZRow: name/Towar input not found');

    await selectProduct(nameInput, code);

    const qtyInput = within('input.input-count')
                  || within('input[name*="unit_count"]')
                  || within('input[name*="ilość"]')
                  || within('input[name*="ilosc"]');
    if (!qtyInput) throw new Error('fillPZRow: quantity input not found');
    setValue(qtyInput, qty);

    const priceInput = within('input.input-price')
                    || within('input[name*="price"]')
                    || within('input[name*="cena"]');
    if (!priceInput) throw new Error('fillPZRow: price input not found');
    setValue(priceInput, price);

    log(`Row filled ✓  code=${code} qty=${qty} price=${price}`);
    return { code, qty, price };
  }

  // ── Public: fillAllRowsFromPayload (convenience) ─────────────────────────

  /**
   * Iterate a PZ_READY-style payload and fill one row per item, adding
   * a new row if needed (best-effort — wFirma's "Add row" button selector
   * varies; tweak ROW_ADD_SELECTOR below if your version differs).
   *
   * The first row in the form is reused; subsequent rows are added by
   * clicking the "+ Dodaj pozycję" button if present.
   */
  const ROW_ADD_SELECTOR = 'a.add, button.add, [data-action="add-row"], .input-add-position';

  async function fillAllRowsFromPayload(payload) {
    if (!payload || !Array.isArray(payload.rows) || payload.rows.length === 0) {
      throw new Error('fillAllRowsFromPayload: payload.rows is empty');
    }
    log(`Filling ${payload.rows.length} rows from payload (${payload.invoice_no || ''})`);

    for (let i = 0; i < payload.rows.length; i++) {
      const row = payload.rows[i];
      const code  = row.product_code;
      const qty   = row.quantity;
      const price = row.net_price_pln;

      // Add a row if this isn't the first one
      if (i > 0) {
        const addBtn = document.querySelector(ROW_ADD_SELECTOR);
        if (!addBtn) {
          throw new Error(`fillAllRowsFromPayload: could not find "+ Dodaj pozycję" button (selector ${ROW_ADD_SELECTOR})`);
        }
        addBtn.click();
        // wait for the new row to materialize
        await new Promise(r => setTimeout(r, 250));
      }

      // Locate the freshest empty row
      const rows = document.querySelectorAll('tr.position, tr.warehouse-document-content, .form-row');
      const targetRow = rows[rows.length - 1] || null;

      try {
        await fillPZRow(targetRow, { code, qty, price });
      } catch (e) {
        warn(`Row ${i + 1} (${code}) failed:`, e.message);
        throw e;     // fail fast, never continue silently
      }
    }
    log(`All ${payload.rows.length} rows filled. Review the form, then click Zapisz manually.`);
  }

  // ── Expose ───────────────────────────────────────────────────────────────
  window.waitFor                 = waitFor;
  window.selectProduct           = selectProduct;
  window.fillPZRow               = fillPZRow;
  window.fillAllRowsFromPayload  = fillAllRowsFromPayload;
  window.PZ_SELECT_VERSION       = '2.0.0';

  log(`autofill_pz_select_v2 loaded — version ${window.PZ_SELECT_VERSION}`);
  log('  exposed: waitFor() · selectProduct() · fillPZRow() · fillAllRowsFromPayload()');
})();
