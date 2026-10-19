/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { InventoryPlanning } from './InventoryPlanning.js';
import { inventoryCommand, loadInventoryPlanningContext, loadReplenishment, loadReplenishmentPolicies, loadWarehouseTasks } from './api.js';
vi.mock('./api.js', () => ({ inventoryCommand: vi.fn(), loadInventoryPlanningContext: vi.fn(), loadReplenishment: vi.fn(), loadReplenishmentPolicies: vi.fn(), loadWarehouseTasks: vi.fn() }));
let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks(); host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.mocked(loadReplenishmentPolicies).mockResolvedValue([]);
  vi.mocked(loadReplenishment).mockResolvedValue([{ id: 'demand-1', sku_code: 'GAUZE', recommended_quantity: '15', snapshot: { available: '8', inventory_position: '8', target_stock: '20', pending_orders: '0' }, status: 'PENDING', reason: '', requisition_number: null }]);
  vi.mocked(loadWarehouseTasks).mockResolvedValue([{ id: 'task-1', task_type: 'RECEIVE', status: 'ASSIGNED', source_type: 'GoodsReceipt', source_id: 'receipt-1', assigned_user: 'operator-1', assigned_name: 'Receiver', evidence: '' }]);
  vi.mocked(loadInventoryPlanningContext).mockResolvedValue({ skus: [{ id: 'sku-1', code: 'GAUZE', name: 'Reviewed gauze', unit: 'pack' }], operators: [{ id: 'operator-1', name: 'Receiver' }], sources: { RECEIVE: [{ id: 'receipt-1', label: 'GRN-1', status: 'UNDER_INSPECTION' }] } });
  vi.mocked(inventoryCommand).mockResolvedValue({});
});
afterEach(() => { act(() => root.unmount()); host.remove(); });
const button = (name: string) => [...document.body.querySelectorAll('button')].find((row) => row.textContent === name)!;
const render = async () => { await act(async () => root.render(<InventoryPlanning tenantId="tenant-a" csrfToken="csrf" locations={[]} />)); };
it('shows planning inputs and source references without invented reorder defaults', async () => {
  await render(); expect(host.textContent).toContain('No reorder policy configured'); expect(host.textContent).toContain('GRN-1');
  await act(async () => button('Configure stock policy').click());
  const modal = document.body.querySelector('[role=dialog]')!;
  expect(modal.textContent).toContain('Safety stock (base units)');
  expect([...modal.querySelectorAll('input[type=number]')].slice(0, 3).every((input) => (input as HTMLInputElement).value === '')).toBe(true);
});
it('reviews stock position and submits demand to the selected tenant', async () => {
  await render(); await act(async () => button('Review demand').click());
  expect(document.body.querySelector('[role=dialog]')?.textContent).toContain('independent procurement approval');
  const input = document.body.querySelector('[role=dialog] input')!;
  act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'Shelf stock and demand verified'); input.dispatchEvent(new Event('input', { bubbles: true })); });
  await act(async () => document.body.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(inventoryCommand).toHaveBeenCalledWith('/api/inventory/replenishment/demand-1/decide/', { approve: true, reason: 'Shelf stock and demand verified' }, 'csrf', 'tenant-a');
});
it('starts an assigned task through its governed transition', async () => {
  await render(); await act(async () => button('start').click());
  await act(async () => document.body.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(inventoryCommand).toHaveBeenCalledWith('/api/inventory/warehouse-tasks/task-1/transition/', { action: 'start', evidence: '' }, 'csrf', 'tenant-a');
});
it('requires an explicit base-unit conversion when configuring a pack barcode', async () => {
  await render(); await act(async () => button('Configure pack barcode').click());
  const modal = document.body.querySelector('[role=dialog]')!;
  expect(modal.textContent).toContain('Base units per scanned pack');
  const conversion = modal.querySelector('input[type=number]') as HTMLInputElement;
  expect(conversion.required).toBe(true); expect(conversion.value).toBe('');
});
