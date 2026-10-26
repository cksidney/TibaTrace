/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import { MfaSecurity } from './MfaSecurity.js';
import type { SessionState } from './api.js';

let container: HTMLDivElement;
let root: Root;
const session: SessionState = { authenticated: true, csrf_token: 'synthetic-csrf',
  mfa: { required: true, enrolled: false, verified: false, reauthenticate: false } };
beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals(); });
function fill(selector: string, value: string) {
  const input = container.querySelector<HTMLInputElement>(selector)!;
  act(() => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
async function submit() {
  await act(async () => { container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
}
it('requires confirmation, renders a private local QR, and makes the user acknowledge recovery storage', async () => {
  const complete = vi.fn();
  const fetcher = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ secret: 'SYNTHETICKEY', qr_svg: '<svg></svg>' })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ recovery_codes: ['synthetic-recovery-code'] })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...session, mfa: { ...session.mfa, enrolled: true, verified: true } })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...session, mfa: { ...session.mfa, enrolled: true, verified: true } })));
  vi.stubGlobal('fetch', fetcher);
  act(() => root.render(<MfaSecurity session={session} onComplete={complete} onSignOut={vi.fn()} />));
  expect(container.textContent).toContain('Protect your account');
  fill('input[type=password]', 'Synthetic-password-789!'); await submit();
  expect(fetcher.mock.calls[0]![0]).toBe('/api/identity/mfa/enroll/');
  expect(fetcher.mock.calls[0]![1].headers['X-CSRFToken']).toBe('synthetic-csrf');
  expect(container.querySelector('img.mfa-qr')?.getAttribute('src')).toMatch(/^data:image\/svg\+xml,/);
  expect(container.querySelector('input[type=password]')).toBeNull();
  fill('input[autocomplete=one-time-code]', '123456'); await submit();
  expect(container.textContent).toContain('Save your recovery codes');
  expect(complete).not.toHaveBeenCalled();
  const button = container.querySelector<HTMLButtonElement>('.primary-button')!;
  expect(button.disabled).toBe(true);
  await act(async () => container.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());
  await act(async () => button.click());
  expect(complete).toHaveBeenCalledOnce();
  expect(container.textContent).not.toContain('synthetic-recovery-code');
});
it('shows a refused code and keeps the workspace gated without echoing credentials', async () => {
  const complete = vi.fn();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Code already used.' }), { status: 400 })));
  act(() => root.render(<MfaSecurity session={{ ...session, mfa: { ...session.mfa!, enrolled: true } }} onComplete={complete} onSignOut={vi.fn()} />));
  fill('input[autocomplete=one-time-code]', '654321'); await submit();
  expect(container.querySelector('[role=alert]')?.textContent).toBe('Code already used.');
  expect(container.textContent).not.toContain('654321');
  expect(complete).not.toHaveBeenCalled();
});
it('requires a new password sign-in after the verification window expires', () => {
  act(() => root.render(<MfaSecurity session={{ ...session, mfa: { ...session.mfa!, enrolled: true, reauthenticate: true } }} onComplete={vi.fn()} onSignOut={vi.fn()} />));
  expect(container.textContent).toContain('Sign in again');
  expect(container.querySelector('form')).toBeNull();
});
