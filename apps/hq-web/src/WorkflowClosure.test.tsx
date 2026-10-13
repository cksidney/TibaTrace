/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CommerceOperations } from './CommerceOperations.js';
import { loadQuotations, setHQTenantContext } from './api.js';

let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); setHQTenantContext(''); vi.unstubAllGlobals(); });

it('follows collection pagination without discarding later rows or tenant headers', async () => {
  setHQTenantContext('tenant-test');
  const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ count:2, next:'/api/sales/quotations/?page=2', results:[{ id:'first' }] }), { status:200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ count:2, next:null, results:[{ id:'second' }] }), { status:200 }));
  vi.stubGlobal('fetch', fetchMock);
  expect((await loadQuotations()).map((row) => row.id)).toEqual(['first', 'second']);
  expect(fetchMock.mock.calls[1]?.[1].headers['X-Tenant-ID']).toBe('tenant-test');
});

it('never forwards tenant headers to an off-origin next page', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ next:'https://unexpected.example/api/sales/quotations/', results:[] }), { status:200 }));
  vi.stubGlobal('fetch', fetchMock);
  await expect(loadQuotations()).rejects.toThrow('Invalid collection pagination URL');
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('does not silently turn a fulfilment load failure into zero business activity', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail:'Forbidden' }), { status:403 })));
  await act(async () => { root.render(<CommerceOperations csrfToken="csrf-test" revision="test" onChanged={async () => {}} />); });
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('403');
  expect(container.textContent).toContain('no empty activity is implied');
});
