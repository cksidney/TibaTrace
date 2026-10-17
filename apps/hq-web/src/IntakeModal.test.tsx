/** @vitest-environment jsdom */
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { IntakeForm } from './IntakeModal.js';
import { IngestionWorkspaceProvider, useIngestionWorkspace } from './IngestionWorkspace.js';
import type { HQOverview } from './api.js';

let container: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals(); });
const click = async (text: string) => act(async () => { [...container.querySelectorAll('button')].find((button) => button.textContent === text)!.click(); });

it('traps focus, restores the trigger and dismisses only when not saving', async () => {
  let finish!: (result: boolean) => void;
  const submit = vi.fn(() => new Promise<boolean>((resolve) => { finish = resolve; }));
  await act(async () => root.render(<IntakeForm title="Add record" submit={submit}><input aria-label="Reference" defaultValue="actual-reference" required /></IntakeForm>));
  const trigger = container.querySelector('button')!; trigger.focus();
  await click('Add record');
  const dialog = container.querySelector('[role="dialog"]')!;
  expect(document.activeElement?.getAttribute('aria-label')).toBe('Reference');
  const controls = [...dialog.querySelectorAll<HTMLButtonElement>('button')];
  controls.at(-1)!.focus();
  act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })));
  expect(document.activeElement).toBe(controls[0]);
  await act(async () => { dialog.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
  act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  await act(async () => { dialog.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
  expect(submit).toHaveBeenCalledTimes(1);
  await act(async () => finish(false));
  expect(container.querySelector('input')?.value).toBe('actual-reference');
  act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(document.body.style.overflow).toBe('');
});

it('keeps a refused draft open and closes after a successful retry', async () => {
  const submit = vi.fn().mockRejectedValueOnce(new Error('Current permission refused')).mockResolvedValueOnce(true);
  await act(async () => root.render(<IntakeForm title="Receive" submit={submit}><input defaultValue="preserved" /></IntakeForm>));
  await click('Receive');
  const save = () => act(async () => { container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
  await save();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('Current permission refused');
  expect(container.querySelector('input')?.value).toBe('preserved');
  await save(); expect(container.querySelector('[role="dialog"]')).toBeNull();
});

const tenants = [{ id: 'tenant-a', name: 'Pharmacy A', status: 'ACTIVE' }, { id: 'tenant-b', name: 'Inactive pharmacy', status: 'SUSPENDED' }].map((tenant) => ({ active_location_count: 0, active_patient_count: 0, active_practitioner_count: 0, active_user_count: 0, country_code: 'KE', slug: tenant.id, time_zone: 'Africa/Nairobi', ...tenant })) satisfies HQOverview['network_items'];
function Launch({ opened }: { opened: () => void }) {
  const open = useIngestionWorkspace();
  return <button type="button" onClick={() => open(opened)}>Register patient</button>;
}
it('requires explicit active tenant choice and never opens intake after a failed scope change', async () => {
  const opened = vi.fn(); const select = vi.fn().mockRejectedValueOnce(new Error('Workspace unavailable')).mockResolvedValueOnce(undefined);
  function Fixture() {
    const [tenant, setTenant] = useState('');
    return <IngestionWorkspaceProvider tenantId={tenant} tenants={tenants} onSelectTenant={async (id) => { await select(id); setTenant(id); }}><Launch opened={opened} /></IngestionWorkspaceProvider>;
  }
  await act(async () => root.render(<Fixture />)); await click('Register patient');
  expect(opened).not.toHaveBeenCalled();
  expect(container.textContent).not.toContain('Inactive pharmacy');
  await act(async () => { const input = container.querySelector('select')!; input.value = 'tenant-a'; input.dispatchEvent(new Event('change', { bubbles: true })); });
  await click('Continue to form'); expect(opened).not.toHaveBeenCalled();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('Workspace unavailable');
  await click('Continue to form'); expect(select).toHaveBeenLastCalledWith('tenant-a'); expect(opened).toHaveBeenCalledTimes(1);
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  await click('Register patient'); expect(opened).toHaveBeenCalledTimes(2);
});
