// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { DhaWorkspace } from './DhaWorkspace.js';

vi.mock('./api.js', () => ({ getHQTenantContext: () => 'tenant-one' }));
let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
afterEach(async () => { if (root) await act(async () => root.unmount()); container?.remove(); vi.unstubAllGlobals(); });

it('shows concrete readiness blockers and keeps activation disabled without credentials', async () => {
  const fetcher = vi.fn(async (url: string, options: RequestInit) => {
    expect((options.headers as Record<string, string>)['X-Tenant-ID']).toBe('tenant-one');
    return new Response(JSON.stringify(url.endsWith('/connections/') ? [{ id: 'connection-one', branch: 'branch-one', branch_name: 'Apex', environment: 'SANDBOX', state: 'DISABLED', configuration: {}, revision: 1, validated_revision: 0,
      readiness: { ready: false, connected: false, blockers: ['Supply client_secret_ref through the server secrets manager.'] } }] : []), { status: 200 });
  });
  vi.stubGlobal('fetch', fetcher);
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  await act(async () => { root.render(<DhaWorkspace csrfToken="csrf" />); });
  expect(container.textContent).toContain('Supply client_secret_ref');
  const activate = [...container.querySelectorAll('button')].find(b => b.textContent === 'Review activation evidence');
  expect(activate?.disabled).toBe(true);
  expect(container.textContent).toContain('Activation pending');
  expect(fetcher.mock.calls.some(([p]) => p.includes('/activate/'))).toBe(false);
});
