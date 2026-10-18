/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { InventoryOperations } from './InventoryOperations.js';
import { inventoryCommand, loadInventoryChanges, loadInventoryValuation } from './api.js';
vi.mock('./api.js', () => ({ inventoryCommand: vi.fn(), loadInventoryChanges: vi.fn(), loadInventoryValuation: vi.fn() }));
let container: HTMLDivElement; let root: Root;
beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks(); container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  vi.mocked(loadInventoryChanges).mockResolvedValue([{ id: 'change-1', kind: 'WRITE_OFF', status: 'PENDING', payload: { quantity: '2' }, reason: 'Damaged packaging evidence', requested_by: 1, requested_by_name: 'counter', decided_by_name: null, decision_reason: '' }]);
  vi.mocked(loadInventoryValuation).mockResolvedValue({ method: 'SPECIFIC_IDENTIFICATION', currency: 'KES', known_value: '0.0000', unvalued_lines: 1, complete: false, note: 'Unknown costs remain unvalued.', rows: [{ balance_id: 'balance-1', sku_id: 'sku-1', sku_code: 'SUP-1', sku_name: 'Gauze', location_id: 'store-1', location: 'Store', batch_id: 'batch-1', batch_number: 'LOT-1', quality_status: 'RELEASED', quantity: '3', unit_cost: null, value: null }] });
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
const button = (text: string) => [...document.body.querySelectorAll('button')].find((item) => item.textContent === text)!;
it('discloses unvalued stock and sends an explicit approval decision to the selected tenant', async () => {
  vi.mocked(inventoryCommand).mockResolvedValue({});
  await act(async () => root.render(<InventoryOperations tenantId="tenant-a" csrfToken="csrf" batches={[]} locations={[]} transfers={[]} onChanged={vi.fn(async () => {})} />));
  expect(container.textContent).toContain('Incomplete acquisition-cost coverage'); expect(container.textContent).toContain('Unvalued');
  await act(async () => button('Review & approve').click());
  expect(document.body.querySelector('[role=dialog]')?.textContent).toContain('Damaged packaging evidence');
  const input = document.body.querySelector('textarea')!;
  act(() => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, 'Independently inspected physical damage'); input.dispatchEvent(new Event('input', { bubbles: true })); });
  await act(async () => document.body.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(inventoryCommand).toHaveBeenCalledWith('/api/inventory/changes/change-1/decide/', { approve: true, reason: 'Independently inspected physical damage' }, 'csrf', 'tenant-a');
});
