/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PosActivationWorkspace } from './PosActivationWorkspace.js';

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

describe('PosActivationWorkspace', () => {
  it('renders pending activations and explicitly issues enrolment challenge code upon approval', async () => {
    const mockRequest = {
      id: 'req-pos-1234',
      tenantId: 'tenant-nairobi-1',
      branchId: 'branch-cbd-1',
      register: 'REG-CBD-01',
      deviceName: 'CBD Front Till 01',
      deviceType: 'DESKTOP_WINDOWS',
      deviceFingerprint: 'sha256:abc1234567890def1234567890',
      requester: 'cashier.mary',
      justification: 'New hardware terminal deployed at CBD checkout 1.',
      state: 'SUBMITTED',
      submittedAt: '2026-10-17T08:00:00Z',
    };

    const fetchMock = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/v1/platform/pos-activations/requests/') && !init?.method) {
        return new Response(JSON.stringify([mockRequest]), { status: 200 });
      }
      if (urlStr.includes('/approve/')) {
        return new Response(
          JSON.stringify({
            ...mockRequest,
            state: 'APPROVED',
            challengeCode: 'CHALLENGE-SECURE-9988',
            challengeExpiresAt: '2026-10-17T08:15:00Z',
          }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify([]), { status: 200 });
    });

    vi.stubGlobal('fetch', fetchMock);

    await act(async () => {
      root.render(
        <PosActivationWorkspace
          csrfToken="test-csrf-token"
          isPlatformOwner={true}
          tenantId="tenant-nairobi-1"
        />,
      );
    });

    // Verify header and metrics
    expect(container.textContent).toContain('POS Terminal Activations & Device Registry');
    expect(container.textContent).toContain('CBD Front Till 01');
    expect(container.textContent).toContain('1 Pending Enrolment');

    // Enter decision rationale
    const textarea = container.querySelector('textarea')!;
    expect(textarea).not.toBeNull();
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
      setter?.call(textarea, 'Approved for hardware till 01 deployment.');
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
      textarea.dispatchEvent(new Event('change', { bubbles: true }));
    });

    // Click Approve button
    const approveBtn = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Approve & Issue Code'),
    )!;
    expect(approveBtn).not.toBeUndefined();

    await act(async () => {
      approveBtn.click();
    });

    // Explicit challenge code must be prominently displayed
    expect(container.textContent).toContain('Enrolment Challenge Code for CBD Front Till 01');
    expect(container.textContent).toContain('CHALLENGE-SECURE-9988');
    expect(container.textContent).toContain('Valid for 15 Minutes');
    expect(container.textContent).toContain('Next Steps for Cashier / Field Technician at the POS Till:');
  });

  it('renders fail-closed state when activation service is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new Error('Network error connecting to activation authority')),
    );

    await act(async () => {
      root.render(
        <PosActivationWorkspace
          csrfToken="test-csrf-token"
          isPlatformOwner={true}
          tenantId="tenant-nairobi-1"
        />,
      );
    });

    expect(container.textContent).toContain('Activation Service Unreachable');
    expect(container.textContent).toContain('Fail Closed');
    const retryBtn = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Retry Connection'),
    );
    expect(retryBtn).not.toBeUndefined();
  });
});
