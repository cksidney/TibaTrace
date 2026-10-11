/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { LegacyItemSetup } from './LegacyItemSetup.js';
import type { LegacySetupPage } from './api.js';

let container: HTMLDivElement;
let root: Root;
const page: LegacySetupPage = {
  summary: { total: 686, positive_stock: 340, negative_stock: 13, details_complete: 0, excluded: 0 },
  count: 1, page: 1, pages: 1, source_date: '2026-10-09', can_edit: true,
  results: [{ id: 'item-1', source_key: 'CODE:1', source_row: 1, legacy_code: '1', proposed_sku_code: 'TE-0001',
    source_name: 'Paracetamol 500mg', source_uom: 'pcs', source_cost: '0.47', source_price: '2.00', source_quantity: '30',
    source_product: { page: 1 }, source_stock: { page: 1 }, source_issues: [], review: {}, status: 'AWAITING_MANAGER',
    missing_details: ['Actual batches and expiry dates'], updated_at: '2026-10-11T07:00:00+03:00', saleable: false }],
};
beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it('keeps imported stock separate and allows an auditable partial manager save', async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(page), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...page.results[0], status: 'IN_PROGRESS' }), { status: 200 }))
    .mockResolvedValue(new Response(JSON.stringify(page), { status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
  await act(async () => { root.render(<LegacyItemSetup csrfToken="csrf-test" />); });
  await act(async () => { await vi.advanceTimersByTimeAsync(250); });
  expect(container.textContent).toContain('340');
  expect(container.textContent).toContain('not saleable stock');
  const button = [...container.querySelectorAll('button')].find((b) => b.textContent === 'Complete details');
  act(() => button?.click());
  expect(container.textContent).toContain('Actual opening-stock batches');
  expect(container.querySelectorAll('.legacy-batch').length).toBe(0);
  await act(async () => { container.querySelector('form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
  const [url, options] = fetchMock.mock.calls[1] as [string, RequestInit];
  expect(url).toContain('/item-1/review/');
  expect(options.headers).toMatchObject({ 'X-CSRFToken': 'csrf-test' });
  expect(JSON.parse(String(options.body))).toEqual({ expected_updated_at: page.results[0].updated_at, review: {
    confirmed_price: null, confirmed_cost: null, counted_quantity: null, counted_on: null,
  } });
  expect(container.textContent).toContain('details saved');
});

it('does not expose edit controls to a reader', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...page, can_edit: false }), { status: 200 })));
  await act(async () => { root.render(<LegacyItemSetup csrfToken="csrf-test" />); });
  await act(async () => { await vi.advanceTimersByTimeAsync(250); });
  const button = [...container.querySelectorAll('button')].find((b) => b.textContent === 'Complete details');
  expect(button?.disabled).toBe(true);
  expect(container.textContent).toContain('Read-only');
});
