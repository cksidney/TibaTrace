/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';

import { ExecutiveDashboard } from './ExecutiveDashboard.js';

it('labels example figures and supports keyboard navigation to the selected workspace', () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const container = document.createElement('div');
  const root = createRoot(container);
  const onNavigate = vi.fn();
  try {
    act(() => root.render(<ExecutiveDashboard csrfToken="test" onNavigate={onNavigate} />));
    expect(container.textContent).toContain('These example values are not live operational data.');
    const card = container.querySelector('[role="button"]');
    expect(card?.getAttribute('tabindex')).toBe('0');
    act(() => card?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
    expect(onNavigate).toHaveBeenCalledWith('Dispensing');
  } finally {
    act(() => root.unmount());
    vi.unstubAllGlobals();
  }
});
