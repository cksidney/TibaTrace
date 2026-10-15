/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CommerceOperations } from './CommerceOperations.js';
import { PrescriptionOrigination } from './PrescriptionOrigination.js';
import * as api from './api.js';

vi.mock('./api.js', () => ({ loadCommerceDesk: vi.fn(), runCommerceCommand: vi.fn(), loadPrescriptionIntakeOptions: vi.fn(), createClinicalWorkflowRecord: vi.fn() }));
let container: HTMLDivElement; let root: Root;
beforeEach(() => { vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.resetAllMocks(); container = document.createElement('div'); document.body.append(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals(); });
const click = async (text: string) => act(async () => { [...container.querySelectorAll('button')].find((button) => button.textContent === text)!.click(); });
async function change(element: HTMLInputElement | HTMLSelectElement, value: string) {
  await act(async () => { Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value')!.set!.call(element, value); element.dispatchEvent(new Event(element.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); });
}
it('moves sales draft intake into a modal and retains the same retry key after a refused save', async () => {
  vi.mocked(api.loadCommerceDesk).mockResolvedValue({ orders: [], quotations: [], tasks: [], sessions: [], packages: [], dispatches: [], skus: [], options: { branches: [{ id: 'branch', name: 'Actual branch' }], customers: [{ id: 'customer', customer_number: 'C-1', legal_name: 'Actual institution' }] } } as unknown as api.CommerceDesk);
  vi.mocked(api.runCommerceCommand).mockRejectedValue(new Error('Order refused by current policy'));
  await act(async () => root.render(<CommerceOperations csrfToken="test-csrf" revision="current" onChanged={async () => {}} />));
  expect(container.querySelector('form')).toBeNull();
  await click('Create sales order draft');
  const dialog = container.querySelector('[role="dialog"]')!;
  const selects = dialog.querySelectorAll('select'); await change(selects[0]!, 'branch'); await change(selects[1]!, 'customer');
  const save = () => act(async () => { dialog.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
  await save(); expect(dialog.querySelector('[role="alert"]')?.textContent).toContain('Order refused');
  const first = vi.mocked(api.runCommerceCommand).mock.calls[0]!;
  expect(first).toEqual(['orders', '', '', { branch: 'branch', customer: 'customer', currency: 'KES', idempotency_key: expect.any(String) }, 'test-csrf']);
  await save(); expect(vi.mocked(api.runCommerceCommand).mock.calls[1]).toEqual(first);
});

it('opens prescription and episode intake separately and retains an uncertain episode key', async () => {
  vi.mocked(api.loadPrescriptionIntakeOptions).mockResolvedValue({ patients: [], practitioners: [], organizations: [], branches: [], skus: [], stores: [{ id: 'store', name: 'Actual store', branch: 'branch' }], verified_prescriptions: [{ id: 'rx', prescription_number: 'VERIFIED-RX', location: 'branch' }], priced_orders: [{ id: 'order', order_number: 'SO-1', branch: 'branch', total: '100' }], search_limited: false });
  vi.mocked(api.createClinicalWorkflowRecord).mockRejectedValue(new Error('Outcome unknown; refresh before retrying'));
  await act(async () => root.render(<PrescriptionOrigination csrfToken="test-csrf" tenantId="tenant-a" onChanged={async () => {}} />));
  expect(container.querySelector('form')).toBeNull();
  await click('Receive prescription'); expect(container.querySelector('[role="dialog"]')?.textContent).toContain('Actual prescription intake');
  expect(container.querySelector('[role="dialog"]')?.textContent).not.toContain('Paid clinical dispensing origination');
  act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  await click('Open dispensing episode'); const dialog = container.querySelector('[role="dialog"]')!;
  const selects = dialog.querySelectorAll('select'); await change(selects[0]!, 'rx'); await change(selects[1]!, 'store'); await change(selects[2]!, 'order');
  const save = () => act(async () => { dialog.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
  await save(); expect(dialog.querySelector('[role="alert"]')?.textContent).toContain('Outcome unknown');
  const first = vi.mocked(api.createClinicalWorkflowRecord).mock.calls[0]!;
  expect(first[1]).toMatchObject({ prescription_id: 'rx', pharmacy_location_id: 'store', sales_order_id: 'order', payment_state: 'PENDING', idempotency_key: expect.any(String) });
  await save(); expect(vi.mocked(api.createClinicalWorkflowRecord).mock.calls[1]).toEqual(first);
});
