import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PrescriptionIntake } from './PrescriptionIntake.js';

let container: HTMLDivElement;
let root: Root;
const base = '/api/pos/dispensing/intake/';
const options = {
  branch: { id: 'branch-1', name: 'Main pharmacy' },
  capabilities: { receive: true, upload: true, read_documents: true, validate: true, review: true, verify: true, open_episode: true },
  patients: [{ id: 'patient-1', name: 'Confirmed patient' }], practitioners: [{ id: 'doctor-1', name: 'Confirmed doctor' }],
  products: [{ id: 'sku-1', name: 'Prescribed medicine', unit: 'tablet' }], stores: [], orders: [],
  feeds: [{ code: 'DHA', available: false, message: 'Tenant connector, credentials and validation required' }],
  max_files: 5, max_file_bytes: 5 * 1024 * 1024, max_total_bytes: 8 * 1024 * 1024,
};
const rx = { id: 'rx-1', reference: 'PAPER-001', patient_name: 'Confirmed patient', patient_number: 'PAT-1', prescriber_name: 'Confirmed doctor', prescription_date: '2026-10-18', source_channel: 'PAPER', status: 'RECEIVED', legal_state: 'PENDING', clinical_state: 'NOT_STARTED', verification_state: 'NOT_VERIFIED', documents: [], items: [] };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function button(label: string) {
  const result = [...container.querySelectorAll('button')].find(item => item.textContent === label);
  if (!result) throw Error(`Missing button ${label}`);
  return result;
}
function field(label: string) {
  const result = [...container.querySelectorAll('label')].find(item => item.firstChild?.textContent === label)?.querySelector('input,select,textarea');
  if (!result) throw Error(`Missing field ${label}`);
  return result as HTMLInputElement;
}
function change(label: string, value: string) {
  const element = field(label);
  const prototype = element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, 'value')?.set?.call(element, value);
  element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
}
function fetcher(write: (path: string, init: RequestInit) => Promise<Response>) {
  return vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (path.includes('/options/')) return response(options);
    if (init?.method === 'POST' || path.includes('/reconcile/')) return write(path, init ?? {});
    return response([]);
  });
}
async function mount(apiFetch: typeof fetch) {
  await act(async () => root.render(<PrescriptionIntake apiFetch={apiFetch} deviceId="device-1" onEpisodeOpened={vi.fn()} />));
  act(() => button('Receive prescription').click());
}
async function prepare() {
  act(() => {
    change('Original RX reference', 'PAPER-001'); change('Patient', 'patient-1'); change('Prescriber', 'doctor-1');
    change('Prescription date', '2026-10-18'); change('Prescription type', 'ACUTE');
    change('Prescribed medicine / pack', 'sku-1'); change('Authorised quantity', '2'); change('Directions as prescribed', 'One tablet twice daily');
    (container.querySelector('input[type="checkbox"]') as HTMLInputElement).click();
  });
}
async function submit() { await act(async () => container.querySelector('form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))); }
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('receives typed source details and preserves all clinical review gates', async () => {
  const api = fetcher(async () => response(rx, 201));
  await mount(api); await prepare(); await submit();
  const write = api.mock.calls.find(([input, init]) => input === base && init?.method === 'POST');
  const command = JSON.parse(String(write?.[1]?.body));
  expect(command).toMatchObject({ device_id: 'device-1', patient: 'patient-1', practitioner: 'doctor-1', prescription_number: 'PAPER-001', original_available: true, items: [{ sku: 'sku-1', quantity: '2', directions: 'One tablet twice daily' }] });
  expect(command.idempotency_key).toBeTruthy();
  expect(container.textContent).toContain('It has not been approved for dispensing');
  expect(button('Pharmacist: verify prescription').disabled).toBe(true);
  expect(container.textContent).not.toContain('Open dispensing episode');
});

it('uploads the original photo through the bounded native JSON transport', async () => {
  const api = fetcher(async () => response(rx, 201));
  await mount(api); await prepare();
  const input = field('Upload scan / photo / PDF');
  Object.defineProperty(input, 'files', { configurable: true, value: [new File(['source-photo'], 'rx.jpg', { type: 'image/jpeg' })] });
  act(() => input.dispatchEvent(new Event('change', { bubbles: true })));
  await submit();
  await act(async () => vi.waitFor(() => expect(api.mock.calls.some(([path, init]) => path === base && init?.method === 'POST')).toBe(true)));
  const command = JSON.parse(String(api.mock.calls.find(([input, init]) => input === base && init?.method === 'POST')?.[1]?.body));
  expect(command.attachments).toEqual([{ name: 'rx.jpg', content_type: 'image/jpeg', content_base64: btoa('source-photo') }]);
});

it('keeps uploads available with a visible deferred scanning notice and source verdict', async () => {
  const notice = 'Malware scanning is deferred. Uploaded sources are recorded as not malware scanned and require pharmacist review.';
  const api = vi.fn<typeof fetch>(async input => String(input).includes('/options/')
    ? response({ ...options, upload_notice: notice })
    : String(input).includes('/rx-1/') ? response({ ...rx, documents: [{ id: 'doc-1', name: 'source.pdf', content_type: 'application/pdf', size_bytes: 20, malware_scan_status: 'NOT_SCANNED' }] })
    : response([rx]));
  await mount(api);
  expect(container.textContent).toContain(notice);
  expect(container.textContent).not.toContain('Files are scanned');
  expect(field('Upload scan / photo / PDF').disabled).toBe(false);
  act(() => button('Close').click());
  await act(async () => button('Received prescriptions').click());
  const open = [...container.querySelectorAll('button')].find(item => item.textContent?.includes('PAPER-001'));
  expect(open).toBeTruthy();
  await act(async () => open?.click());
  expect(container.textContent).toContain('source.pdf · Not malware scanned');
});

it('reconciles an unknown intake result before allowing an unchanged retry', async () => {
  let writes = 0;
  const api = fetcher(async path => {
    if (path.includes('/reconcile/')) return response({ found: false, prescription: null });
    if (++writes === 1) throw Error('Connection lost after send');
    return response(rx, 201);
  });
  await mount(api); await prepare(); await submit();
  expect(container.textContent).toContain('Intake outcome unknown');
  expect(field('Patient').disabled || field('Patient').closest('fieldset')?.disabled).toBe(true);
  expect([...container.querySelectorAll('button')].some(item => item.textContent === 'Retry original intake')).toBe(false);
  await act(async () => button('Check original intake').click());
  await act(async () => button('Retry original intake').click());
  const commands = api.mock.calls.filter(([input, init]) => input === base && init?.method === 'POST');
  expect(commands).toHaveLength(2);
  expect(commands[0]?.[1]?.body).toBe(commands[1]?.[1]?.body);
});

it('renders the generated manual intake record as escaped text for review', async () => {
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:intake-record') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  const source = '{"notes":"<img src=x onerror=alert(1)>","original_available":true}';
  const api = fetcher(async path => path.endsWith('/source-document/')
    ? response({ name: 'intake.txt', content_type: 'text/plain', content_base64: btoa(source) })
    : response({ ...rx, documents: [{ id: 'doc-1', name: 'intake.txt', content_type: 'text/plain', size_bytes: source.length, malware_scan_status: 'NOT_APPLICABLE' }] }, 201));
  await mount(api); await prepare(); await submit();
  await act(async () => button('intake.txt · Intake record').click());
  expect(container.querySelector('.pos-rx-preview pre')?.textContent).toBe(source);
  expect(container.querySelector('.pos-rx-preview img')).toBeNull();
  expect(container.querySelector('.pos-rx-preview iframe')).toBeNull();
});

it('rejects oversized source files and leaves unconfigured tenant feeds disabled', async () => {
  const api = fetcher(async () => response(rx)); await mount(api);
  expect((container.querySelector('option[value="DHA"]') as HTMLOptionElement).disabled).toBe(true);
  const input = field('Upload scan / photo / PDF');
  const file = new File(['x'], 'large.pdf', { type: 'application/pdf' });
  Object.defineProperty(file, 'size', { value: 6 * 1024 * 1024 });
  Object.defineProperty(input, 'files', { value: [file] });
  act(() => input.dispatchEvent(new Event('change', { bubbles: true })));
  expect(container.textContent).toContain('5 MB each and 8 MB total');
  expect(api.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
});

it('offers upload fallback when the camera cannot be opened', async () => {
  const getUserMedia = vi.fn().mockRejectedValue(Error('Permission denied'));
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } });
  await mount(fetcher(async () => response(rx)));
  await act(async () => button('Take prescription photo').click());
  expect(getUserMedia).toHaveBeenCalledWith(expect.objectContaining({ audio: false, video: expect.any(Object) }));
  expect(container.textContent).toContain('Upload a prescription photo or scanned file instead');
});

it('previews a PDF with an explicit PDF MIME and rejects active HTML disguised by its name', async () => {
  const createObjectURL = vi.fn<(blob: Blob) => string>(() => 'blob:rx-preview');
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  await mount(fetcher(async () => response(rx)));
  const input = field('Upload scan / photo / PDF');
  Object.defineProperty(input, 'files', { configurable: true, value: [new File(['%PDF-1.4 source %%EOF'], 'source.pdf')] });
  act(() => input.dispatchEvent(new Event('change', { bubbles: true })));
  act(() => button('Preview source.pdf').click());
  expect(createObjectURL.mock.calls[0]?.[0]).toMatchObject({ type: 'application/pdf' });
  expect(container.querySelector('iframe')?.title).toBe('Original prescription PDF');
  Object.defineProperty(input, 'files', { value: [new File(['<script>active content</script>'], 'fake.pdf', { type: 'text/html' })] });
  act(() => input.dispatchEvent(new Event('change', { bubbles: true })));
  expect(container.textContent).toContain('Choose JPEG, PNG or PDF source files');
  expect(container.textContent).not.toContain('Preview fake.pdf');
});
