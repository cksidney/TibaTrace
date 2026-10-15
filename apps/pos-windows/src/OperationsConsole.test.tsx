import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const workflow = vi.hoisted(() => ({
  state: { selected: {
    id: 'episode-1', dispensing_number: 'DISP-1', status: 'PAID', payment_state: 'PAID',
    collected_at: null, allergies: [], lines: [], counselling_status: 'NOT_STARTED',
  }, queue: [], gate: { canTakePayment: false, canConfirmCollection: true, blockedReason: '' }, busy: false, notice: null },
  refreshQueue: vi.fn(), select: vi.fn(), refresh: vi.fn(), takePayment: vi.fn(),
  confirmCollection: vi.fn(), recordCounselling: vi.fn(), journal: null,
}));
vi.mock('./state/usePosWorkflow.js', () => ({ usePosWorkflow: () => workflow }));
vi.mock('./state/useClinicalScreening.js', () => ({ useClinicalScreening: () => ({ summary: null, result: null, error: '', refresh: vi.fn() }) }));
vi.mock('./components/tibatrace/OperationalStatusBar.js', () => ({ OperationalStatusBar: () => null }));
vi.mock('./components/tibatrace/RetailWorkspace.js', () => ({ RetailWorkspace: () => <div>Retail workspace</div> }));

import { OperationsConsole } from './App.js';

describe('console keyboard navigation', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    vi.clearAllMocks();
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
    const apiFetch = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ effective_capabilities: [] }), { status: 200 }));
    await act(async () => root.render(<OperationsConsole
      session={{ authenticated: true, activationValid: true, tenantId: 'tenant-1', userId: 'operator-1', deviceId: 'device-1', apiBaseUrl: '' }}
      apiFetch={apiFetch} onLogout={async () => undefined} onActivationRefresh={async () => undefined}
    />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });

  function key(value: string, ctrlKey = false) {
    act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: value, ctrlKey, bubbles: true, cancelable: true })));
  }

  function button(label: string) {
    const match = Array.from(container.querySelectorAll('button')).find(item => item.textContent?.trim() === label);
    if (!match) throw new Error('Missing button: ' + label);
    return match;
  }

  it('opens handover with F10 without performing payment or collection', () => {
    key('F4');
    expect(container.querySelector('#collection-workspace')).toBeNull();
    key('F10');
    expect(container.querySelector('#collection-workspace')).not.toBeNull();
    expect(workflow.takePayment).not.toHaveBeenCalled();
    expect(workflow.confirmCollection).not.toHaveBeenCalled();
  });

  it('keeps console shortcuts inactive behind the workstation lock', () => {
    act(() => button('Lock').click());
    expect(container.querySelector('[aria-labelledby="workstation-lock-title"]')).not.toBeNull();
    key('F4'); key('Escape'); key('r', true);
    expect(container.querySelector('#collection-workspace')).not.toBeNull();
    expect(workflow.select).not.toHaveBeenCalled();
    expect(workflow.refresh).not.toHaveBeenCalled();
  });

  it('opens help from other workspaces and does not navigate the clinical episode', () => {
    act(() => button('retail').click());
    key('F1');
    const modal = container.querySelector('[aria-labelledby="keyboard-help-title"]');
    expect(modal).not.toBeNull();
    expect(modal?.textContent).toContain('F10');
    expect(modal?.textContent).not.toContain('F9');
    key('Escape');
    expect(container.querySelector('[aria-labelledby="keyboard-help-title"]')).toBeNull();
    key('r', true);
    expect(workflow.refresh).not.toHaveBeenCalled();
  });
});
