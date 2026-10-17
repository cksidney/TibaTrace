/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PosActivationConsole } from './PosActivationConsole.js';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const request = { id:'request-1', tenantId:'tenant-1', branchId:'branch-1', deviceId:'device-1', deviceName:'Counter', state:'SUBMITTED', deviceType:'DESKTOP_WINDOWS', deviceFingerprint:'stable-installation-fingerprint', requestingUserId:'manager-1', requestedRegister:'REG1', businessJustification:'Primary counter', appVersion:'1.0.11' };
let root: Root;
let container: HTMLDivElement;
const button = (label: string) => Array.from(container.querySelectorAll('button')).find(e => e.textContent?.includes(label));
async function change(element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string) {
  const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(prototype, 'value')?.set?.call(element,value); element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? 'change' : 'input', {bubbles:true})); });
}
async function render(apiFetch: typeof fetch, owner = true) {
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  await act(async () => root.render(<PosActivationConsole apiFetch={apiFetch} userId={owner ? 'owner-1' : 'manager-1'} userRole={owner ? 'PLATFORM_OWNER' : 'MANAGER'} userCapabilities={owner ? ['platform.pos_activation.approve'] : ['identity.manage']} isPlatformOwnerContext={owner} tenantId="tenant-1" deviceId="device-1" fingerprint="stable-installation-fingerprint" />));
}
afterEach(async () => { if (root) await act(async () => root.unmount()); container?.remove(); vi.useRealTimers(); });
const json = (value: unknown, status=200) => new Response(JSON.stringify(value), {status,headers:{'Content-Type':'application/json'}});

describe('activation request and recovery', () => {
  it.each([
    ['Approve & Issue Challenge','approve','SUBMITTED'], ['Reject Request','reject','SUBMITTED'], ['Revoke Device','revoke','ACTIVATED'],
    ['Issue renewal / recovery code','issue-code','ACTIVATED'], ['Suspend device','suspend','ACTIVATED'], ['Resume device','resume','SUSPENDED'], ['Release register for replacement','release-register','REVOKED'],
  ])('routes %s through a reasoned action', async (label, endpoint, state) => {
    const fetcher = vi.fn<typeof fetch>(async (_input, init) => json(init?.method === 'POST' ? {challengeCode:'one-time-code'} : [{...request,state}]));
    await render(fetcher);
    await act(async () => button(label)?.click());
    expect(container.querySelector('[role=dialog]')).not.toBeNull();
    await change(container.querySelector('textarea')!, 'Independent review completed');
    await act(async () => container.querySelector('form')?.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
    expect(fetcher.mock.calls.find(([,init]) => init?.method === 'POST')?.[0]).toBe(`/api/v1/platform/pos-activations/requests/request-1/${endpoint}/`);
    expect(container.textContent).toContain('one-time-code');
  });

  it('loads scoped branch/register choices and retains a refused draft', async () => {
    const fetcher = vi.fn<typeof fetch>(async (path,init) => init?.method === 'POST' ? json({detail:'Register reserved by another request'},400) : String(path).endsWith('/options/') ? json({branches:[{id:'branch-1',code:'BR1',name:'Branch One'}],registers:[{id:'reg-1',branchId:'branch-1',code:'REG1',name:'Front counter',available:true},{id:'reg-2',branchId:'branch-1',code:'BUSY',name:'Occupied',available:false}]}) : json([]));
    await render(fetcher,false);
    await act(async () => button('Submit Activation Request')?.click());
    const selects = container.querySelectorAll('select');
    await change(selects[0]!, 'branch-1'); await change(selects[1]!, 'REG1');
    expect(selects[1]?.textContent).not.toContain('BUSY');
    await change(container.querySelector('input')!, 'Counter Two'); await change(container.querySelector('textarea')!, 'Primary counter for supervised trading');
    await act(async () => container.querySelector('form')?.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
    expect(container.querySelector('input')?.value).toBe('Counter Two');
    expect(container.textContent).toContain('Register reserved by another request');
    const body = JSON.parse(fetcher.mock.calls.find(([,init]) => init?.method === 'POST')?.[1]?.body as string);
    expect(body).toMatchObject({branch_id:'branch-1',requested_register:'REG1',device_id:'device-1',device_fingerprint:'stable-installation-fingerprint',device_type:'DESKTOP_WINDOWS'});
  });

  it('refreshes remote approval and enrols an active installation with a recovery code', async () => {
    let state = 'SUBMITTED';
    const fetcher = vi.fn<typeof fetch>(async (path) => String(path).endsWith('/options/') ? json({branches:[],registers:[]}) : json([{...request,state,challengeAvailable:state === 'ACTIVATED'}]));
    await render(fetcher,false); expect(button('Complete device enrolment')).toBeUndefined();
    state='ACTIVATED'; await act(async () => button('Refresh approval status')?.click());
    expect(button('Complete device enrolment')).toBeDefined();
  });

  it('does not let a requester independently approve their own device', async () => {
    await render(vi.fn<typeof fetch>(async () => json([{...request,requestingUserId:'owner-1'}])));
    expect(button('Approve & Issue Challenge')?.disabled).toBe(true);
  });
});
