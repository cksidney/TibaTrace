/** @vitest-environment jsdom */

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { StockTransferDialog, StockTransfersTab } from './App.js';

const findButton = (container: HTMLElement, label: string) => (
  Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes(label))
);

describe('stock transfer request dialog', () => {
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
  });

  it('keeps the trigger actionable when tenant setup is incomplete', () => {
    const onDialog = vi.fn();

    act(() => {
      root.render(
        <StockTransfersTab balances={[]} locations={[]} onDialog={onDialog} transfers={[]} />,
      );
    });

    const trigger = findButton(container, 'New transfer request');
    expect(trigger).toBeDefined();
    expect(trigger?.disabled).toBe(false);
    expect(trigger?.getAttribute('aria-haspopup')).toBe('dialog');

    act(() => trigger?.click());

    expect(onDialog).toHaveBeenCalledWith({ kind: 'create' });
    expect(container.textContent).toContain('Setup required before submission.');
  });

  it('opens a guided blocker state and prevents an invalid submission', () => {
    const onOpenInventoryTab = vi.fn();

    act(() => {
      root.render(
        <StockTransferDialog
          balances={[]}
          csrfToken="csrf-test"
          dialog={{ kind: 'create' }}
          locations={[]}
          onClose={vi.fn()}
          onOpenInventoryTab={onOpenInventoryTab}
          onSaved={vi.fn(async () => undefined)}
          tenantId="tenant-test"
        />,
      );
    });

    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
    expect(container.textContent).toContain('Complete transfer setup');
    expect(container.textContent).toContain('Add at least two active inventory locations');
    expect(container.textContent).toContain('Release stock into an active source location');

    const submit = findButton(container, 'Setup required');
    expect(submit?.disabled).toBe(true);

    act(() => findButton(container, 'Review inventory locations')?.click());
    expect(onOpenInventoryTab).toHaveBeenCalledWith('locations');
  });
});
