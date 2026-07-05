// Wave 4 Item 1A — reducer unit test for CURRENCY-AWARE Sales Receivable.
//
// The repo has no JS test runner wired into `make verify`, so this is a
// standalone Node test (run:  node --test service/tests/js/). It loads the REAL
// `accReceivableByCurrency` from accounting-hub.jsx by esbuild-transforming the
// file and evaluating it with window/React stubs, then asserts:
//   * per-currency sums are correct
//   * cross-currency amounts are NEVER summed into one number
//   * unavailable rows and unparseable values are skipped
//
// Run:  node --test service/tests/js/test_acc_receivable_reducer.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import vm from 'node:vm';
import { createRequire } from 'node:module';

const __dirname = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const esbuild = require(resolve(__dirname, '../../frontend/proforma-v2/node_modules/esbuild'));

function loadReducer() {
  const src = readFileSync(resolve(__dirname, '../../app/static/v2/accounting-hub.jsx'), 'utf8');
  const js = esbuild.transformSync(src, { loader: 'jsx' }).code;
  const sandbox = { window: {}, React: new Proxy({}, { get: () => () => null }), console };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(js, sandbox);
  const fn = sandbox.window._accReceivableByCurrency;
  assert.equal(typeof fn, 'function', 'accReceivableByCurrency must be exposed on window');
  // The function runs in a separate VM realm, so its output objects have a
  // foreign prototype and fail strict deepEqual. JSON-normalize into this realm.
  return (rows) => JSON.parse(JSON.stringify(fn(rows)));
}

const reduce = loadReducer();

test('single currency: sums outstanding within the currency', () => {
  const out = reduce([
    { balance_available: true, currency: 'USD', open: '100.00', open_by_currency: { USD: '100.00' } },
    { balance_available: true, currency: 'USD', open: '50.50',  open_by_currency: { USD: '50.50' } },
  ]);
  assert.deepEqual(out, [{ currency: 'USD', amount: '150.50' }]);
});

test('MIXED currencies are NOT summed into one number', () => {
  const out = reduce([
    { balance_available: true, currency: 'USD', open: '100.00', open_by_currency: { USD: '100.00' } },
    { balance_available: true, currency: 'EUR', open: '40.00',  open_by_currency: { EUR: '40.00' } },
    { balance_available: true, currency: 'PLN', open: '10.00',  open_by_currency: { PLN: '10.00' } },
  ]);
  // Three separate entries — never a combined 150.00.
  assert.equal(out.length, 3);
  const map = Object.fromEntries(out.map(r => [r.currency, r.amount]));
  assert.deepEqual(map, { EUR: '40.00', PLN: '10.00', USD: '100.00' });
  // Prove no cross-currency total leaked in.
  const combined = out.reduce((a, r) => a + parseFloat(r.amount), 0);
  assert.equal(combined, 150.0);                 // math check only — NOT rendered
  assert.ok(!out.some(r => r.amount === '150.00'), 'no single mixed total entry');
});

test('multi-currency client (open_by_currency with 2 ccys) split correctly', () => {
  const out = reduce([
    { balance_available: true, currency: 'multi', open: null,
      open_by_currency: { USD: '200.00', EUR: '25.00' } },
    { balance_available: true, currency: 'USD', open: '5.00', open_by_currency: { USD: '5.00' } },
  ]);
  const map = Object.fromEntries(out.map(r => [r.currency, r.amount]));
  assert.deepEqual(map, { EUR: '25.00', USD: '205.00' });
});

test('unavailable rows and unparseable values are skipped', () => {
  const out = reduce([
    { balance_available: false, currency: 'USD', open: '999.00' },          // skipped
    { balance_available: true,  currency: 'USD', open: 'n/a', open_by_currency: { USD: 'n/a' } }, // skipped
    { balance_available: true,  currency: 'USD', open: '12.00', open_by_currency: { USD: '12.00' } },
  ]);
  assert.deepEqual(out, [{ currency: 'USD', amount: '12.00' }]);
});

test('empty / nullish input yields empty (no fabricated total)', () => {
  assert.deepEqual(reduce([]), []);
  assert.deepEqual(reduce(null), []);
});

test('fallback path: single-ccy row without open_by_currency uses {currency, open}', () => {
  const out = reduce([{ balance_available: true, currency: 'GBP', open: '77.00' }]);
  assert.deepEqual(out, [{ currency: 'GBP', amount: '77.00' }]);
});
