/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';

import { PosActivationConsole } from './PosActivationConsole.js';

describe('activation governance routing', () => {
  it.each(['Reject Request', 'Revoke Device', 'Approve & Issue Challenge'])('sends %s to its own endpoint', async (label) => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement('div');
    const root = createRoot(container);
    const apiFetch = vi.fn<typeof fetch>(async (_input, init) => new Response(JSON.stringify(init?.method === 'POST' ? { challengeCode: 'one-time-code' } : [{
      id: 'request-1', tenantId: 'tenant-1', branchId: 'branch-1', deviceName: 'Counter', state: 'SUBMITTED',
      deviceType: 'DESKTOP_WINDOWS', deviceFingerprint: 'stable-installation-fingerprint', requestingUserId: 'manager-1',
      requestedRegister: 'REG1', requesterEmailSnapshot: 'manager@example.test', requesterRole: 'MANAGER',
      businessJustification: 'Primary counter', appVersion: '1.0.3', osName: 'Windows', correlationId: 'request-1',
    }]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const button = (text: string) => Array.from(container.querySelectorAll('button')).find((element) => element.textContent?.includes(text));
    try {
      await act(async () => root.render(<PosActivationConsole apiFetch={apiFetch} userId="owner-1" userRole="PLATFORM_OWNER"
        userCapabilities={['platform.pos_activation.approve']} isPlatformOwnerContext tenantId="tenant-1" deviceId="device-1" />));
      await act(async () => button(label)?.click());
      const input = container.querySelector('input');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
      await act(async () => {
        setter?.call(input, 'Independent review completed');
        input?.dispatchEvent(new Event('input', { bubbles: true }));
      });
      await act(async () => button('Confirm')?.click());
      const mutation = apiFetch.mock.calls.find(([, init]) => init?.method === 'POST');
      const action = label.startsWith('Reject') ? 'reject' : label.startsWith('Revoke') ? 'revoke' : 'approve';
      expect(mutation?.[0]).toBe(`/api/v1/platform/pos-activations/requests/request-1/${action}/`);
      if (action === 'approve') expect(container.textContent).toContain('one-time-code');
    } finally {
      await act(async () => root.unmount());
    }
  });
});
