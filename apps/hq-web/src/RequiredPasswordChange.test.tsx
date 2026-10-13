/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { RequiredPasswordChange } from './RequiredPasswordChange.js';

describe('required password change', () => {
  let container: HTMLDivElement;
  let root: Root;
  const currentPassword = 'Synthetic-temporary-password';
  const newPassword = 'Synthetic-new-password-12';

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

  function render(onChanged = vi.fn(async () => undefined), onSignOut = vi.fn(async () => undefined)) {
    act(() => root.render(<RequiredPasswordChange csrfToken="csrf-test" onChanged={onChanged} onSignOut={onSignOut} />));
    return { onChanged, onSignOut };
  }

  function input(id: string) {
    const element = container.querySelector<HTMLInputElement>(`#${id}`);
    if (!element) throw new Error(`Missing input ${id}`);
    return element;
  }

  function fill(id: string, value: string) {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(input(id), value);
      input(id).dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  async function submit() {
    await act(async () => {
      container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
  }

  it('binds the dedicated readable card/form styling and accessible password fields', () => {
    render();
    expect(container.querySelector('main.auth-page.required-password-page')).not.toBeNull();
    expect(container.querySelector('section.required-password-card')?.getAttribute('aria-labelledby')).toBe('required-password-heading');
    expect(container.querySelector('form.required-password-form')).not.toBeNull();
    expect(container.querySelectorAll('.required-password-field')).toHaveLength(3);
    expect(container.querySelector('h1')?.textContent).toBe('Secure your account');
    for (const id of ['temporary-password', 'replacement-password', 'replacement-confirm']) {
      expect(input(id).type).toBe('password');
      expect(input(id).required).toBe(true);
      expect(container.querySelector(`label[for="${id}"]`)).not.toBeNull();
    }
    expect(input('temporary-password').autocomplete).toBe('current-password');
    expect(input('replacement-password').autocomplete).toBe('new-password');
    expect(input('replacement-password').minLength).toBe(12);
    expect(input('replacement-password').getAttribute('aria-describedby')).toBe('replacement-password-help');
    expect(container.querySelector('.required-password-actions')?.querySelectorAll('button')).toHaveLength(2);
  });

  it('reports a mismatch without sending or exposing either password', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    render();
    fill('temporary-password', currentPassword);
    fill('replacement-password', newPassword);
    fill('replacement-confirm', 'Synthetic-different-password');
    await submit();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('New passwords do not match.');
    expect(container.textContent).not.toContain(currentPassword);
    expect(container.textContent).not.toContain(newPassword);
  });

  it('preserves the CSRF-protected API request and prevents edits/repeated submits while busy', async () => {
    let resolveResponse!: (response: Response) => void;
    const response = new Promise<Response>((resolve) => { resolveResponse = resolve; });
    const fetchMock = vi.fn().mockReturnValue(response);
    vi.stubGlobal('fetch', fetchMock);
    const { onChanged } = render();
    fill('temporary-password', currentPassword);
    fill('replacement-password', newPassword);
    fill('replacement-confirm', newPassword);
    await submit();
    expect(container.querySelector('form')?.getAttribute('aria-busy')).toBe('true');
    expect([...container.querySelectorAll('input, button')].every((element) => (element as HTMLInputElement).disabled)).toBe(true);
    await submit();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/api/identity/password/change/', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': 'csrf-test' },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
    await act(async () => { resolveResponse(new Response(null, { status: 204 })); });
    expect(onChanged).toHaveBeenCalledTimes(1);
    expect(input('temporary-password').value).toBe('');
    expect(input('replacement-password').value).toBe('');
    expect(input('replacement-confirm').value).toBe('');
    expect(container.querySelector('form')?.getAttribute('aria-busy')).toBe('false');
  });

  it('shows a server refusal and leaves the fields available for a safe retry', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Current password was not accepted.' }), { status: 400 })));
    const { onChanged } = render();
    fill('temporary-password', currentPassword);
    fill('replacement-password', newPassword);
    fill('replacement-confirm', newPassword);
    await submit();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('Current password was not accepted.');
    expect(input('temporary-password').disabled).toBe(false);
    expect(onChanged).not.toHaveBeenCalled();
  });

  it.each([
    [{ new_password: ['Ensure this field has at least 12 characters.'], request_id: 'request-test' },
      'new password: Ensure this field has at least 12 characters.'],
    [{ detail: ['This password is too common.', 'This password is entirely numeric.'] },
      'This password is too common. This password is entirely numeric.'],
  ])('shows the actual validation error so the password can be corrected', async (payload, message) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 400 })));
    const { onChanged } = render();
    fill('temporary-password', currentPassword);
    fill('replacement-password', newPassword);
    fill('replacement-confirm', newPassword);
    await submit();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(message);
    expect(container.querySelector('[role="alert"]')?.textContent).not.toContain('request-test');
    expect(input('temporary-password').disabled).toBe(false);
    expect(onChanged).not.toHaveBeenCalled();
  });

  it('keeps sign out available without making a password-change request', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const { onSignOut } = render();
    act(() => container.querySelector<HTMLButtonElement>('button[type="button"]')!.click());
    expect(onSignOut).toHaveBeenCalledTimes(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
