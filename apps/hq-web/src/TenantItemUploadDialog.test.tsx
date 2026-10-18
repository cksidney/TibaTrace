/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { TenantItemUploadDialog } from './TenantItemUploadDialog.js';
import { downloadOpeningStocktakeTemplate, importTenantItemList } from './api.js';
import type { TenantItemImportResult } from './api.js';

vi.mock('./api.js', () => ({ importTenantItemList: vi.fn(), downloadOpeningStocktakeTemplate: vi.fn() }));

let container: HTMLDivElement;
let root: Root;
const imported = vi.fn();
const preview: TenantItemImportResult = {
  dry_run: true, received: 1, valid: true, errors: [], ready_to_stage: 1,
  created: 0, existing: 0, import_id: null, import_code: 'CSV-abc',
};

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  act(() => root.render(<TenantItemUploadDialog tenantId="tenant-a" csrfToken="csrf" onClose={vi.fn()} onImported={imported} />));
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

function button(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll('button')].find((element) => element.textContent === label);
  if (!found) throw new Error(`Missing button: ${label}`);
  return found;
}

async function choose(csv: string, filename = 'items.csv') {
  const file = new File([csv], filename, { type: 'text/csv' });
  Object.defineProperty(file, 'text', { value: () => Promise.resolve(csv) });
  const input = container.querySelector<HTMLInputElement>('input[type=file]')!;
  Object.defineProperty(input, 'files', { configurable: true, value: [file] });
  await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })); });
}

it('previews the exact tenant file before importing and downloading its populated count sheet', async () => {
  vi.mocked(importTenantItemList).mockResolvedValueOnce(preview).mockResolvedValueOnce({
    ...preview, dry_run: false, created: 1, import_id: 'import-1',
  });
  vi.mocked(downloadOpeningStocktakeTemplate).mockResolvedValue();
  expect(button('Import validated items').disabled).toBe(true);
  await choose('item_code,item_name,sales_unit,selling_price\n0001,Gauze,piece,\n');
  expect(container.textContent).toContain('0001');
  expect(button('Import validated items').disabled).toBe(true);
  await act(async () => { button('Preview import').click(); });
  expect(importTenantItemList).toHaveBeenLastCalledWith(
    [{ item_code: '0001', item_name: 'Gauze', sales_unit: 'piece', selling_price: '', _source_row: 2 }],
    expect.any(String), 'items.csv', true, 'csrf', 'tenant-a',
  );
  expect(button('Import validated items').disabled).toBe(false);
  await act(async () => { button('Import validated items').click(); });
  expect(imported).toHaveBeenCalledWith(expect.objectContaining({ import_id: 'import-1', created: 1 }));
  expect(container.textContent).toContain('Item list imported');
  await act(async () => { button('Download stock-take sheet').click(); });
  expect(downloadOpeningStocktakeTemplate).toHaveBeenCalledWith('tenant-a', 'import-1');
});

it('keeps the apply button disabled for row errors and invalidates a preview when metadata changes', async () => {
  vi.mocked(importTenantItemList).mockResolvedValueOnce({ ...preview, valid: false,
    errors: [{ row: 2, field: 'item_code', value: 'ITEM-1', message: 'Already exists in this tenant.' }],
  }).mockResolvedValueOnce(preview);
  await choose('item_code,item_name,sales_unit\nITEM-1,Gauze,piece\n');
  await act(async () => { button('Preview import').click(); });
  expect(container.textContent).toContain('Already exists in this tenant.');
  expect(button('Import validated items').disabled).toBe(true);
  await act(async () => { button('Preview import').click(); });
  expect(button('Import validated items').disabled).toBe(false);
  const date = container.querySelector<HTMLInputElement>('input[type=date]')!;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(date, '2026-10-01');
    date.dispatchEvent(new Event('input', { bubbles: true }));
  });
  expect(button('Import validated items').disabled).toBe(true);
  expect(imported).not.toHaveBeenCalled();
});

it('rejects unknown columns and a replacement file invalidates the previous preview', async () => {
  vi.mocked(importTenantItemList).mockResolvedValue(preview);
  await choose('item_code,item_name,sales_unit\nITEM-1,Gauze,piece\n');
  await act(async () => { button('Preview import').click(); });
  expect(button('Import validated items').disabled).toBe(false);
  await choose('item_code,item_name,sales_unit,unexpected\nITEM-1,Gauze,piece,discard me\n');
  expect(container.textContent).toContain('Unrecognised columns: unexpected');
  expect(button('Import validated items').disabled).toBe(true);
  expect(button('Preview import').disabled).toBe(true);
});

it('keeps an idempotent retry usable without re-creating records', async () => {
  vi.mocked(importTenantItemList).mockResolvedValue({ ...preview, import_id: 'prior-import', existing: 1 });
  await choose('item_code,item_name,sales_unit\nITEM-1,Gauze,piece\n');
  await act(async () => { button('Preview import').click(); });
  expect(container.textContent).toContain('already imported');
  await act(async () => { button('Import validated items').click(); });
  expect(imported).toHaveBeenCalledWith(expect.objectContaining({ created: 0, existing: 1, import_id: 'prior-import' }));
});
