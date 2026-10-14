/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import type { HQOverview } from './api.js';
import { RegulatoryWorkspace } from './RegulatoryWorkspace.js';

const overview: HQOverview = {
  allowed_views: ['overview', 'regulatory'], is_platform_owner: false,
  attention_items: [], data_summary: [], metrics: [], network_items: [],
  generated_at: '2026-10-14T10:00:00Z', is_platform_overview: false,
  scope_description: 'Tenant workspace', scope_label: 'Tenant', tenant_id: 'tenant-a',
  tenant_name: 'Tenant A', user_name: 'Tenant manager',
};
let container: HTMLDivElement;
let root: Root;
let requests: string[];

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  requests = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    requests.push(String(url));
    return new Response(JSON.stringify([]), { status: 200 });
  }));
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

it('keeps tenant response but hides global regulator tabs/actions and never fetches the owner register', async () => {
  await act(async () => root.render(<RegulatoryWorkspace csrfToken="synthetic-csrf" overview={overview} />));
  expect(container.querySelectorAll('[role="tab"]')).toHaveLength(1);
  expect(container.querySelector('[role="tab"]')?.textContent).toContain('Tenant response');
  expect(container.textContent).not.toContain('Ingest alert');
  expect(requests).toEqual(['/api/nif/recalls/impacts/']);
});

it('retains global regulator tools for an explicit owner inside a selected tenant', async () => {
  await act(async () => root.render(<RegulatoryWorkspace csrfToken="synthetic-csrf" overview={{ ...overview, is_platform_owner: true }} />));
  expect(container.querySelectorAll('[role="tab"]')).toHaveLength(2);
  expect(container.textContent).toContain('Ingest alert');
  expect(requests).toContain('/api/nif/platform/recalls/');
});

it('removes an open owner-only intake dialog when fresh grants revoke ownership', async () => {
  await act(async () => root.render(<RegulatoryWorkspace csrfToken="synthetic-csrf" overview={{ ...overview, is_platform_owner: true }} />));
  act(() => container.querySelector<HTMLButtonElement>('.regulatory-header-actions button')!.click());
  expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  await act(async () => root.render(<RegulatoryWorkspace csrfToken="synthetic-csrf" overview={overview} />));
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  expect(container.querySelectorAll('[role="tab"]')).toHaveLength(1);
  expect(container.querySelector('[aria-selected="true"]')?.textContent).toContain('Tenant response');
});
