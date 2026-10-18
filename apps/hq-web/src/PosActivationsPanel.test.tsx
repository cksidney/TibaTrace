/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PosActivationsPanel } from './PosActivationsPanel.js';
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let container: HTMLDivElement;
const row = {id:'a1',tenantId:'t1',branchId:'b1',register:'REG1',deviceName:'Till One',state:'ACTIVATED',requester:'Manager',justification:'Front counter'};
const json = (data: unknown,status=200) => new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
const button = (label: string) => Array.from(container.querySelectorAll('button')).find(e => e.textContent?.includes(label));
async function render(owner:boolean, currentUserName?: string) {
  container=document.createElement('div');document.body.append(container);root=createRoot(container);
  await act(async () => root.render(<PosActivationsPanel tenantId="t1" csrfToken="csrf-test" isPlatformOwner={owner} currentUserName={currentUserName ?? ''} />));
}
afterEach(async () => { if(root) await act(async () => root.unmount());container?.remove();vi.unstubAllGlobals(); });
describe('HQ activation scope and governance', () => {
  it('loads tenant tracking through the tenant endpoint without owner actions',async () => {
    const fetcher=vi.fn<typeof fetch>(async () => json([row]));vi.stubGlobal('fetch',fetcher);await render(false);
    expect(fetcher.mock.calls[0]?.[0]).toContain('/api/v1/tenant/pos-activations/requests/');
    expect(button('Suspend device')).toBeUndefined(); expect(container.textContent).toContain('Complete enrolment on the approved POS');
  });
  it('issues recovery codes through a scoped modal and retains refused rationale',async () => {
    let refusal=true;
    const fetcher=vi.fn<typeof fetch>(async (_path,init) => init?.method==='POST' ? refusal ? json({detail:'Independent review is required'},403) : json({challengeCode:'replacement-code',challengeExpiresAt:'2026-10-18T10:00:00Z'}) : json([row]));
    vi.stubGlobal('fetch',fetcher);await render(true);
    await act(async () => button('Issue renewal / recovery code')?.click());
    const textarea=document.querySelector('textarea');
    await act(async () => {Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')?.set?.call(textarea,'Reviewed original installation identity');textarea?.dispatchEvent(new Event('input',{bubbles:true}));});
    await act(async () => document.querySelector('form')?.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
    expect(textarea?.value).toBe('Reviewed original installation identity'); expect(document.body.textContent).toContain('Independent review is required');
    refusal=false;
    await act(async () => document.querySelector('form')?.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
    const mutation=fetcher.mock.calls.find(([,init]) => init?.method==='POST');
    expect(mutation?.[0]).toBe('/api/v1/platform/pos-activations/requests/a1/issue-code/');
    expect(mutation?.[1]?.headers).toMatchObject({'X-Tenant-ID':'t1','X-CSRFToken':'csrf-test'});
    expect(container.textContent).toContain('replacement-code');expect(document.querySelector('[role=dialog]')).toBeNull();
  });
  it('disables independent-review actions on the owner’s own request',async () => {
    vi.stubGlobal('fetch',vi.fn<typeof fetch>(async () => json([{...row,state:'SUBMITTED',requester:'Owner'}])));
    await render(true,'Owner');
    expect(button('Approve & issue code')?.disabled).toBe(true);
    expect(button('Reject request')?.disabled).toBe(true);
    expect(container.textContent).toContain('A different platform owner must review requests you submitted.');
  });
});
