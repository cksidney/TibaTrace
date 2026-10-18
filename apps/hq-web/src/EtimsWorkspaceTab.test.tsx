/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { setHQTenantContext } from './api.js';
import { EtimsWorkspaceTab } from './EtimsWorkspaceTab.js';

it('scopes fiscal monitoring to the selected pharmacy and blocks uncertain-invoice retry', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); setHQTenantContext('tenant-a');
  const fetcher = vi.fn(async (url: string) => new Response(JSON.stringify(url.includes('/profile/') ? { branches: [{ id: 'branch-a', code: 'MAIN', name: 'Main', enabled: false, message: 'Setup pending', mapped_item_count: 0 }] } : { results: [{ id: 'fiscal-1', branch_id: 'branch-a', branch_name: 'Main', source_kind: 'RETAIL', source_id: 'sale-a', status: 'UNKNOWN', attempts: 1, invoice_number: 123, receipt: null, can_prepare: false }] }), { status: 200 }));
  vi.stubGlobal('fetch', fetcher);
  const c = document.createElement('div'); const root = createRoot(c);
  try {
    await act(async () => root.render(<EtimsWorkspaceTab csrfToken="csrf" />));
    expect(fetcher).toHaveBeenCalledWith('/api/taxation/profile/', expect.objectContaining({ headers: expect.objectContaining({ 'X-Tenant-ID': 'tenant-a' }) }));
    expect(c.textContent).toContain('UNKNOWN');
    expect(c.textContent).not.toContain('Prepare invoice');
    expect(c.textContent).not.toContain('KRA eTIMS FISCAL RECEIPT');
    const detail = Array.from(c.querySelectorAll('button')).find(b => b.textContent === 'View fiscal details');
    await act(async () => detail?.click());
    expect(c.textContent).toContain('Accepted fiscal receipt evidence is not yet available.');
  } finally { act(() => root.unmount()); setHQTenantContext(''); vi.unstubAllGlobals(); }
});

it('shows a refused fiscal load instead of reporting an empty queue', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); setHQTenantContext('tenant-a');
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 403 })));
  const c = document.createElement('div'); const root = createRoot(c);
  try {
    await act(async () => root.render(<EtimsWorkspaceTab csrfToken="csrf" />));
    expect(c.querySelector('[role="alert"]')?.textContent).toContain('could not be loaded');
    expect(c.textContent).not.toContain('No fiscal submissions');
  } finally { act(() => root.unmount()); setHQTenantContext(''); vi.unstubAllGlobals(); }
});
