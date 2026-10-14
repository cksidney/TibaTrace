/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CommercialPricing } from './CommercialPricing.js';
import * as api from './api.js';

vi.mock('./api.js', () => ({
  loadCommercialLists: vi.fn(), loadCommercialEntries: vi.fn(), loadCommercialPriceOptions: vi.fn(),
  commandCommercialList: vi.fn(), saveCommercialEntry: vi.fn(), saveCommercialList: vi.fn(),
}));
let container: HTMLDivElement; let root: Root;
const draft = { id: 'list-1', code: 'B2B', name: 'Commercial prices', currency: 'KES', effective_from: '2026-10-14', effective_to: null, is_default: false, status: 'DRAFT',
  governance: { state: 'SUBMITTED', content_hash: 'exact-reviewed-hash', submission_id: 'submission', approved_by: null } };
const opts = { skus: [{ id: 'sku-1', sku_code: 'SKU-1', display_name: 'Confirmed item', sales_unit: 'tablet', status: 'ACTIVE' }], more_skus: false, can_edit: true, can_approve: true, can_publish: true };
beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.resetAllMocks();
  vi.mocked(api.loadCommercialLists).mockResolvedValue([draft]);
  vi.mocked(api.loadCommercialEntries).mockResolvedValue([]);
  vi.mocked(api.loadCommercialPriceOptions).mockResolvedValue(opts);
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
async function render(tenant = 'tenant-a') {
  act(() => { root.render(<CommercialPricing tenantId={tenant} csrfToken="csrf-test" />); });
  // Options are deliberately loaded by a timer. Wait for the actual enabled
  // workspace rather than assuming a fixed delay means the form is mounted.
  for (let attempt = 0; attempt < 100; attempt += 1) {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
    if (container.querySelector('fieldset:not([disabled]) select')) return;
  }
  throw new Error('Commercial pricing workspace did not finish loading.');
}
async function change(element: HTMLInputElement | HTMLSelectElement, value: string) {
  if (!element) throw new Error('The requested commercial pricing control is not mounted.');
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value')!.set!;
    setter.call(element, value); element.dispatchEvent(new Event(element.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
  });
}
const button = (text: string) => [...container.querySelectorAll('button')].find((item) => item.textContent === text)!;
async function select() { await change(container.querySelector('select')!, 'list-1'); }

it('waits for the options-backed workspace when the initial request is delayed', async () => {
  vi.mocked(api.loadCommercialPriceOptions).mockImplementation(async () => {
    await new Promise((resolve) => setTimeout(resolve, 80));
    return opts;
  });
  await render(); await select();
  expect(container.querySelector('select')?.value).toBe('list-1');
  expect(button('Independent approval')).toBeDefined();
});

it('binds review to actual contents and tenant, retaining the retry key on uncertainty', async () => {
  await render(); await select();
  await change(container.querySelector('input[maxlength="1000"]')!, 'Checked the actual prices');
  vi.mocked(api.commandCommercialList).mockRejectedValue(new Error('Connection interrupted'));
  await act(async () => button('Independent approval').click());
  const first = vi.mocked(api.commandCommercialList).mock.calls[0]!;
  expect(first.slice(0, 2)).toEqual(['list-1', 'govern']);
  expect(first[2]).toMatchObject({ operation: 'approve', expected_content_hash: 'exact-reviewed-hash', reason: 'Checked the actual prices' });
  expect(first.slice(3)).toEqual(['tenant-a', 'csrf-test']);
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('command key is retained');
  await act(async () => button('Independent approval').click());
  expect(vi.mocked(api.commandCommercialList).mock.calls[1]![2]).toEqual(first[2]);
});

it('keeps the draft form mounted during debounced SKU search', async () => {
  await render(); await select();
  const input = container.querySelector('input[placeholder="Code or item name"]')!;
  await change(input as HTMLInputElement, 'Confirmed');
  expect(container.querySelector('input[placeholder="Code or item name"]')).toBe(input);
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 280)); });
  expect(api.loadCommercialPriceOptions).toHaveBeenLastCalledWith('tenant-a', 'Confirmed', expect.any(AbortSignal));
});

it('does not offer live price edits or create access to a review-only actor', async () => {
  vi.mocked(api.loadCommercialLists).mockResolvedValue([{ ...draft, status: 'ACTIVE', governance: { ...draft.governance, state: 'ACTIVE' } }]);
  vi.mocked(api.loadCommercialPriceOptions).mockResolvedValue({ ...opts, can_edit: false, can_publish: false });
  await render(); await select();
  expect(container.textContent).not.toContain('Save draft price');
  expect(container.textContent).not.toContain('Create unapproved draft');
  expect(container.textContent).not.toContain('Archive list with reason');
});

it('clears draft and reason when changing tenant and does not render an empty success on API failure', async () => {
  await render(); await select(); await change(container.querySelector('input[maxlength="1000"]')!, 'Tenant A reason');
  vi.mocked(api.loadCommercialLists).mockRejectedValue(new Error('403 Forbidden'));
  await render('tenant-b');
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('403 Forbidden');
  expect(container.textContent).not.toContain('Tenant A reason');
  expect(container.querySelector('select')?.value).toBe('');
});
