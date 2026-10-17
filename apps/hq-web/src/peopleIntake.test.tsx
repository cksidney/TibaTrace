/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from './App.js';
import { setHQTenantContext } from './api.js';

let container: HTMLDivElement; let root: Root;
let requests: { path: string; method: string; tenant: string; payload: Record<string, unknown> }[];
let refuse = false;
const workspace = {
  generated_at: '2026-10-15T20:00:00Z',
  business_modules: ['patients', 'practitioners', 'customers'].map((key) => ({ key, domain: 'people', title: key, description: '', records: [], count: 0, page: 1, pages: 1 })),
  people: { counts: { patients: 0, active_patients: 0, practitioners: 0, verified_practitioners: 0, customers: 0, active_customers: 0 }, patients: [], practitioners: [], customers: [] },
  clinical: { counts: {}, encounters: [], conditions: [], observations: [], knowledge_releases: [], code_systems: [], value_sets: [], fhir_idempotency_records: [] },
};
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('scrollTo', vi.fn());
  sessionStorage.clear(); setHQTenantContext(''); requests = []; refuse = false;
  window.history.replaceState(null, '', '/#people');
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).split('?')[0]!; const headers = init?.headers as Record<string, string> | undefined;
    const tenant = headers?.['X-Tenant-ID'] ?? ''; const method = init?.method ?? 'GET';
    const payload = init?.body ? JSON.parse(String(init.body)) : {};
    requests.push({ path, method, tenant, payload });
    let body: unknown = [];
    if (method === 'POST') return new Response(JSON.stringify(refuse ? { detail: 'Registration refused by current policy' } : { id: 'created', ...payload }), { status: refuse ? 403 : 201 });
    if (path === '/api/identity/session/') body = { authenticated: true, csrf_token: 'test-csrf', user: { username: 'reviewer', is_platform_owner: true, tenant_id: '' } };
    if (path === '/api/hq/overview/') body = { allowed_views: ['overview', 'people', 'clinical'], is_platform_owner: true, show_pos_handoff: false, attention_items: [], data_summary: [], generated_at: '2026-10-15T20:00:00Z', is_platform_overview: !tenant, metrics: [], network_items: [{ id: 'tenant-a', name: 'Pharmacy A', status: 'ACTIVE' }], scope_description: 'Synthetic fixture', scope_label: tenant ? 'Tenant' : 'Platform', tenant_id: tenant, tenant_name: 'Review workspace', user_name: 'Reviewer' };
    if (path === '/api/hq/workspace/') body = workspace;
    if (path === '/api/health/') body = { status: 'ok' };
    if (path === '/api/prescriptions/intake-options/') body = { patients: [], practitioners: [], branches: [], organizations: [], skus: [], stores: [], verified_prescriptions: [], priced_orders: [], search_limited: false };
    return new Response(JSON.stringify(body), { status: 200 });
  }));
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); setHQTenantContext(''); sessionStorage.clear(); vi.unstubAllGlobals(); });
async function change(element: HTMLInputElement | HTMLSelectElement, value: string) {
  await act(async () => { Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value')!.set!.call(element, value); element.dispatchEvent(new Event(element.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); });
}
const click = async (text: string, scope: ParentNode = container) => act(async () => { [...scope.querySelectorAll('button')].find((button) => button.textContent?.trim() === text)!.click(); });
async function launch(text: string) {
  await act(async () => root.render(<App />));
  await click(text, container.querySelector('[aria-label="People intake"]')!);
  const scope = container.querySelector('[role="dialog"]')!;
  expect(scope.textContent).toContain('Choose an intake workspace');
  expect(requests.filter((item) => item.method === 'POST')).toHaveLength(0);
  await change(scope.querySelector('select')!, 'tenant-a'); await click('Continue to form', scope);
  return container.querySelector('[role="dialog"]')!;
}
function input(dialog: Element, label: string) { return [...dialog.querySelectorAll('label')].find((item) => item.querySelector('span')?.textContent === label)!.querySelector('input')!; }

it('opens patient intake from platform scope, posts to the selected tenant and preserves a refused draft', async () => {
  const dialog = await launch('Register patient'); expect(dialog.textContent).toContain('Internal reference');
  await change(input(dialog, 'Internal reference'), 'ACTUAL-001'); await change(input(dialog, 'First name'), 'Test'); await change(input(dialog, 'Last name'), 'Patient');
  refuse = true; await click('Register patient', dialog);
  expect(container.querySelector('[role="dialog"]')).toBe(dialog);
  expect(dialog.querySelector('[role="alert"]')?.textContent).toContain('Registration refused');
  expect(input(dialog, 'Internal reference').value).toBe('ACTUAL-001');
  expect(requests.find((item) => item.method === 'POST')).toMatchObject({ path: '/api/patients/', tenant: 'tenant-a', payload: { first_name: 'Test', last_name: 'Patient' } });
  refuse = false; await click('Register patient', dialog); expect(container.querySelector('[role="dialog"]')).toBeNull();
});

it('opens unverified practitioner intake from platform scope and uses the authoritative endpoint', async () => {
  const dialog = await launch('Register practitioner');
  await change(input(dialog, 'First name'), 'Test'); await change(input(dialog, 'Last name'), 'Prescriber');
  await change(input(dialog, 'Registration / licence number'), 'TEST-REG'); await change(input(dialog, 'Licensing body'), 'Test register');
  await click('Register unverified', dialog);
  expect(requests.find((item) => item.method === 'POST')).toMatchObject({ path: '/api/practitioners/', tenant: 'tenant-a', payload: { registration_number: 'TEST-REG' } });
  expect(container.querySelector('[role="dialog"]')).toBeNull();
});

it('opens commercial customer intake from platform scope instead of sending an unscoped request', async () => {
  const dialog = await launch('Register commercial customer');
  const required = [...dialog.querySelectorAll<HTMLInputElement>('input[required]')]; expect(required).toHaveLength(2);
  await change(required[0]!, 'CUST-TEST'); await change(required[1]!, 'Test institution'); await click('Register Customer', dialog);
  expect(requests.find((item) => item.method === 'POST')).toMatchObject({ path: '/api/customers/customers/', tenant: 'tenant-a', payload: { customer_number: 'CUST-TEST', legal_name: 'Test institution' } });
});

it('keeps the requested prescription modal through the asynchronous tenant workspace refresh', async () => {
  window.history.replaceState(null, '', '/#clinical');
  await act(async () => root.render(<App />));
  expect(requests.some((item) => item.path === '/api/prescriptions/intake-options/')).toBe(false);
  await click('Receive prescription'); const picker = container.querySelector('[role="dialog"]')!;
  await change(picker.querySelector('select')!, 'tenant-a'); await click('Continue to form', picker);
  const dialog = container.querySelector('[role="dialog"]')!;
  expect(dialog.textContent).toContain('Actual prescription intake');
  expect(requests.filter((item) => item.path === '/api/prescriptions/intake-options/')).toEqual([expect.objectContaining({ tenant: 'tenant-a', method: 'GET' })]);
});
