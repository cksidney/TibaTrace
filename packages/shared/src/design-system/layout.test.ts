import { describe, expect, it } from 'vitest';

import { autoColumns, breakpoint, viewportAtMost, viewportClassFor } from './layout.js';

describe('viewportClassFor', () => {
  it('classifies the device widths the clients are actually opened on', () => {
    expect(viewportClassFor(360)).toBe('compact'); // small Android phone
    expect(viewportClassFor(390)).toBe('compact'); // common phone portrait
    expect(viewportClassFor(768)).toBe('medium'); // tablet portrait
    expect(viewportClassFor(1024)).toBe('expanded'); // tablet landscape
    expect(viewportClassFor(1366)).toBe('wide'); // till panel / laptop
    expect(viewportClassFor(1920)).toBe('wide');
  });

  it('treats each breakpoint as the first width of the next class', () => {
    expect(viewportClassFor(breakpoint.compact - 1)).toBe('compact');
    expect(viewportClassFor(breakpoint.compact)).toBe('medium');
    expect(viewportClassFor(breakpoint.medium)).toBe('expanded');
    expect(viewportClassFor(breakpoint.expanded)).toBe('wide');
  });
});

describe('viewportAtMost', () => {
  it('orders the classes from narrow to wide', () => {
    expect(viewportAtMost('compact', 'medium')).toBe(true);
    expect(viewportAtMost('medium', 'medium')).toBe(true);
    expect(viewportAtMost('expanded', 'medium')).toBe(false);
    expect(viewportAtMost('wide', 'expanded')).toBe(false);
  });
});

describe('autoColumns', () => {
  it('clamps the track floor to the container so a narrow screen cannot overflow', () => {
    expect(autoColumns(220)).toBe('repeat(auto-fit, minmax(min(100%, 220px), 1fr))');
  });
});
