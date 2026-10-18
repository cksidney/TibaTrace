/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CountSheetUpload } from './CountSheetUpload.js';
import { inventoryCommand } from './api.js';
vi.mock('./api.js', () => ({ inventoryCommand: vi.fn() }));
let container: HTMLDivElement; let root: Root;
const saved = vi.fn();
beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks(); container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  act(() => root.render(<CountSheetUpload opening path="/api/medicines/initial-setup/stocktake-upload/" csrfToken="csrf" tenantId="tenant-a" onClose={vi.fn()} onSaved={saved} />));
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
const button = (text: string) => [...document.body.querySelectorAll('button')].find((item) => item.textContent === text)!;
async function choose(csv: string) {
  const file = new File([csv], 'count.csv', { type: 'text/csv' }); Object.defineProperty(file, 'text', { value: () => Promise.resolve(csv) });
  const input = document.body.querySelector<HTMLInputElement>('input[type=file]')!; Object.defineProperty(input, 'files', { configurable: true, value: [file] });
  await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })); });
}
it('requires preview of exact tenant counts and invalidates it after selecting another sheet', async () => {
  vi.mocked(inventoryCommand).mockResolvedValue({ items: 1 });
  expect(button('Save validated counts').disabled).toBe(true);
  await choose('item_id,expected_updated_at,counted_quantity,counted_on\nitem-1,timestamp,0,2026-10-18\n');
  await act(async () => button('Validate counts').click());
  expect(inventoryCommand).toHaveBeenLastCalledWith('/api/medicines/initial-setup/stocktake-upload/', { rows: [{ item_id: 'item-1', expected_updated_at: 'timestamp', counted_quantity: '0', counted_on: '2026-10-18' }], dry_run: true }, 'csrf', 'tenant-a');
  expect(button('Save validated counts').disabled).toBe(false);
  await choose('item_id,expected_updated_at,counted_quantity,counted_on\nitem-2,timestamp,2,2026-10-18\n');
  expect(button('Save validated counts').disabled).toBe(true);
  await act(async () => button('Validate counts').click());
  await act(async () => button('Save validated counts').click());
  expect(saved).toHaveBeenCalledOnce();
});
it('keeps the sheet open with server validation errors and prevents apply', async () => {
  vi.mocked(inventoryCommand).mockRejectedValue(new Error('Row 2: manager evidence changed. Download a new sheet.'));
  await choose('item_id,expected_updated_at,counted_quantity,counted_on\nitem-1,old,3,2026-10-18\n');
  await act(async () => button('Validate counts').click());
  expect(document.body.textContent).toContain('manager evidence changed');
  expect(button('Save validated counts').disabled).toBe(true); expect(saved).not.toHaveBeenCalled();
});
