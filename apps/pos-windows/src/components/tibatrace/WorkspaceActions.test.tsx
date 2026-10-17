import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PrintCentre, type PosPrintJob } from './PrintCentre.js';
import { RetailWorkspace } from './RetailWorkspace.js';
import { OperationalStatusBar } from './OperationalStatusBar.js';

let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  container = document.createElement('div'); document.body.append(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals(); });
function button(label: string) {
  const found = Array.from(container.querySelectorAll('button')).find(item => item.textContent?.includes(label));
  if (!found) throw new Error(`Missing ${label}`);
  return found;
}
function response(body: unknown) { return new Response(JSON.stringify(body), { status: 200 }); }

it('filters the real print queue without mutating or losing jobs', async () => {
  const fetcher = vi.fn<typeof fetch>();
  const jobs = ['QUEUED', 'RETRY_REQUIRED', 'PRINTED'].map((status, index) => ({
    id: String(index), document_number: `RECEIPT-${index}`, document_type: 'RECEIPT', printer: '',
    transport: 'SIMULATOR', status, copy_classification: 'ORIGINAL', copy_number: 1,
    reprint_reason: '', requested_at: '2026-10-15T12:00:00Z', attempt_count: 0,
    failure_code: '', failure_message: '', printed_at: null, cancellation_reason: '',
  })) as PosPrintJob[];
  await act(async () => root.render(<PrintCentre apiFetch={fetcher} deviceId="device-1" initialJobs={jobs} autoRefresh={false} />));
  expect(container.querySelectorAll('article')).toHaveLength(3);
  act(() => button('Need attention').click());
  expect(container.querySelectorAll('article')).toHaveLength(1);
  expect(container.querySelector('article')?.textContent).toContain('RECEIPT-1');
  act(() => button('Printed').click());
  expect(container.querySelector('article')?.textContent).toContain('RECEIPT-2');
  act(() => button('All documents').click());
  expect(container.querySelectorAll('article')).toHaveLength(3);
  expect(fetcher).not.toHaveBeenCalled();
});

it('starts a scoped sale once even when clicked twice before the response', async () => {
  let resolveDraft!: (value: Response) => void;
  const draft = new Promise<Response>(resolve => { resolveDraft = resolve; });
  const fetcher = vi.fn<typeof fetch>(async (input) => String(input).includes('/stores/')
    ? response([{ id: 'store-1', name: 'Main pharmacy', status: 'ACTIVE', location_type: 'PHARMACY' }]) : draft);
  await act(async () => root.render(<RetailWorkspace apiFetch={fetcher} deviceId="till-1" />));
  const start = button('Start new sale');
  expect(container.querySelector('.pos-retail-search')?.contains(start)).toBe(true);
  await act(async () => { start.click(); start.click(); });
  const writes = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST');
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0]?.[1]?.body))).toEqual({ device_id: 'till-1', store_id: 'store-1' });
  await act(async () => resolveDraft(response({ id: 'sale-1', transaction_number: 'SALE-1', register_code: 'REG-1', state: 'DRAFT', lines: [], currency: 'KES', subtotal: '0', tax_total: '0', discount_total: '0', total: '0' })));
  expect(container.textContent).toContain('SALE-1');
  expect((container.querySelector('input[placeholder="Scan barcode"]') as HTMLInputElement).disabled).toBe(false);
});

it('keeps operational warnings discoverable and routes to the register', async () => {
  const open = vi.fn();
  const fetcher = vi.fn<typeof fetch>(async () => response({ readiness: 'ATTENTION', notices: ['Open the business day before trading.'], register: { code: 'REG-1', branch_code: 'BR-1' } }));
  await act(async () => root.render(<OperationalStatusBar apiFetch={fetcher} deviceId="till-1" onOpenWorkspace={open} />));
  expect(container.textContent).toContain('Operational attention required');
  act(() => button('View status').click());
  expect(container.textContent).toContain('Open the business day before trading.');
  act(() => button('Open Register').click());
  expect(open).toHaveBeenCalledWith('register');
});
