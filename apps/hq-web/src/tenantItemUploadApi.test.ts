/** @vitest-environment jsdom */
import { afterEach, expect, it, vi } from 'vitest';
import { downloadOpeningStocktakeTemplate, importTenantItemList, setHQTenantContext } from './api.js';

afterEach(() => { setHQTenantContext(''); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('posts uploaded items using the selected tenant even when the global workspace differs', async () => {
  setHQTenantContext('other-workspace');
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ valid: true, errors: [] }), { status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
  const rows = [{ item_code: '0001', item_name: 'Gauze', sales_unit: 'piece', _source_row: 2 }];
  await importTenantItemList(rows, '2026-10-01', 'items.csv', true, 'csrf-test', 'selected-tenant');
  expect(fetchMock).toHaveBeenCalledWith('/api/medicines/initial-setup/import/', expect.objectContaining({
    method: 'POST', credentials: 'include',
    headers: expect.objectContaining({ 'X-Tenant-ID': 'selected-tenant', 'X-CSRFToken': 'csrf-test' }),
    body: JSON.stringify({ rows, source_date: '2026-10-01', source_filename: 'items.csv', dry_run: true }),
  }));
});

it('downloads a whole source without carrying the table search/page filters into the request', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response('item_id,item_name,counted_quantity\r\n1,Gauze,\r\n', {
    status: 200, headers: { 'Content-Disposition': 'attachment; filename="opening-tenant-a.csv"' },
  }));
  vi.stubGlobal('fetch', fetchMock);
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockReturnValue('blob:csv') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  const anchor = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  await downloadOpeningStocktakeTemplate('tenant-a', 'source-1');
  expect(fetchMock).toHaveBeenCalledWith('/api/medicines/initial-setup/stocktake-template/?import_id=source-1',
    expect.objectContaining({ credentials: 'include', headers: expect.objectContaining({ 'X-Tenant-ID': 'tenant-a' }) }));
  expect(anchor).toHaveBeenCalledOnce();
  expect((anchor.mock.contexts[0] as HTMLAnchorElement).download).toBe('opening-tenant-a.csv');
});

it('surfaces a refused download without generating a file', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Inventory management permission is required.' }), { status: 403 })));
  await expect(downloadOpeningStocktakeTemplate('tenant-a')).rejects.toThrow('Inventory management permission');
});
