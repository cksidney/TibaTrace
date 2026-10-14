/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Dashboard } from './App.js';
import type { HQOverview } from './api.js';
import { accessibleHqViews, canOpenHqDestination } from './navigationAccess.js';

const mountedOwnerView = vi.hoisted(() => vi.fn());
vi.mock('./PlatformOwnerConsole.js', () => ({ PlatformOwnerConsole: () => { mountedOwnerView('platform_owner'); return <div>Owner console mounted</div>; } }));
vi.mock('./IntegrationWorkspace.js', () => ({ IntegrationWorkspace: () => { mountedOwnerView('integration'); return <div>Integration mounted</div>; } }));
vi.mock('./ExecutiveDashboard.js', () => ({ ExecutiveDashboard: () => { mountedOwnerView('executive'); return <div>Executive mounted</div>; } }));

const tenant: HQOverview = {
  allowed_views: ['overview', 'inventory', 'reports', 'access'], is_platform_owner: false, show_pos_handoff: false,
  attention_items: [{ label: 'Network signal', detail: 'Fixture', value: 1, tone: 'rose', href: '#network' }],
  data_summary: [], generated_at: '2026-10-14T10:00:00Z', is_platform_overview: false, metrics: [], network_items: [],
  scope_description: 'Tenant workspace', scope_label: 'Tenant', tenant_id: 'tenant-a', tenant_name: 'Tenant A', user_name: 'Tenant Manager',
};

describe('HQ navigation boundary', () => {
  let container: HTMLDivElement;
  let root: Root;
  let requests: string[];

  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    vi.stubGlobal('scrollTo', vi.fn());
    requests = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      requests.push(String(url));
      return new Response(JSON.stringify({ status: 'ok' }), { status: 200 });
    }));
    window.history.replaceState(null, '', '/#overview');
    mountedOwnerView.mockClear();
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });

  async function render(overview = tenant) {
    await act(async () => root.render(<Dashboard
      csrfToken="synthetic-csrf" isPlatformAdmin={overview.is_platform_owner === true} overview={overview}
      onRefresh={async () => undefined} onSelectTenant={async () => undefined} onSignOut={async () => undefined}
      refreshFailed={false} refreshing={false} selectedTenantId="tenant-a" tenantOptions={[]}
    />));
  }

  function sidebarLinks() {
    return Array.from(container.querySelectorAll('nav[aria-label="Headquarters navigation"] a'), link => link.getAttribute('href'));
  }

  it('shows only granted tenant modules in desktop/mobile navigation and shortcuts', async () => {
    await render();
    expect(sidebarLinks()).toEqual(['#overview', '#inventory', '#reports', '#access']);
    for (const href of ['#network', '#executive', '#integration', '#platform_owner', '/api/docs/', '/pos/']) {
      expect(container.querySelector(`a[href="${href}"]`)).toBeNull();
    }
    expect(container.textContent).toContain('Tenant users & permissions');
    expect(container.textContent).not.toContain('System controls');
    expect(requests.some(path => path.includes('/nif/platform/'))).toBe(false);
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="Open navigation"]')!.click());
    expect(container.querySelector('.sidebar-open')).not.toBeNull();
    expect(sidebarLinks()).toEqual(['#overview', '#inventory', '#reports', '#access']);
  });

  it('filters command search and account links by the same grants', async () => {
    await render();
    act(() => container.querySelector<HTMLButtonElement>('.search-trigger')!.click());
    const search = container.querySelector('.command-results')!;
    expect(Array.from(search.querySelectorAll('a'), link => link.getAttribute('href'))).toEqual(['#overview', '#inventory', '#reports', '#access']);
    act(() => container.querySelector<HTMLButtonElement>('.user-trigger')!.click());
    const menu = container.querySelector('#hq-account-menu')!;
    expect(menu.querySelector('a[href="#access"]')).not.toBeNull();
    expect(menu.querySelector('a[href="/api/docs/"]')).toBeNull();
    expect(menu.textContent).not.toContain('System controls');
  });

  it.each(['network', 'executive', 'integration', 'platform_owner'])('guards bookmarked and manually typed #%s before owner pages mount', async view => {
    window.history.replaceState(null, '', `/#${view}/details`);
    await render();
    expect(window.location.hash).toBe('#overview');
    expect(mountedOwnerView).not.toHaveBeenCalled();
    await act(async () => {
      window.location.hash = `#${view}`;
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });
    expect(window.location.hash).toBe('#overview');
    expect(mountedOwnerView).not.toHaveBeenCalled();
    expect(requests.some(path => /nif\/platform|pharmacy-network/.test(path))).toBe(false);
  });

  it('retains owner navigation even while the owner operates inside a tenant', async () => {
    const owner = { ...tenant, is_platform_owner: true, allowed_views: ['overview', 'network', 'executive', 'integration', 'platform_owner', 'access'], show_pos_handoff: true };
    await render(owner);
    expect(sidebarLinks()).toContain('#network');
    expect(sidebarLinks()).toContain('#platform_owner');
    expect(container.querySelector('a[href="/api/docs/"]')).not.toBeNull();
    await act(async () => { window.location.hash = '#platform_owner'; window.dispatchEvent(new HashChangeEvent('hashchange')); });
    expect(mountedOwnerView).toHaveBeenCalledWith('platform_owner');
  });

  it('fails closed without new access metadata and never infers ownership from scope', async () => {
    const { allowed_views: _allowed, is_platform_owner: _owner, show_pos_handoff: _pos, ...oldOverview } = tenant;
    await render({ ...oldOverview, is_platform_overview: true });
    expect(sidebarLinks()).toEqual(['#overview']);
    expect(canOpenHqDestination(oldOverview, '/api/docs/')).toBe(false);
  });

  it('fences owner keys even if tenant menu metadata contains them', () => {
    const forged = { ...tenant, allowed_views: ['overview', 'network', 'executive', 'integration', 'platform_owner', 'inventory'] };
    expect([...accessibleHqViews(forged)]).toEqual(['overview', 'inventory']);
    expect(canOpenHqDestination(forged, '#network/detail')).toBe(false);
  });

  it('immediately unmounts a revoked owner route when a fresh overview arrives', async () => {
    window.history.replaceState(null, '', '/#platform_owner');
    await render({ ...tenant, is_platform_owner: true, allowed_views: ['overview', 'platform_owner'] });
    expect(container.textContent).toContain('Owner console mounted');
    await render(tenant);
    expect(container.textContent).not.toContain('Owner console mounted');
    expect(window.location.hash).toBe('#overview');
  });
});
