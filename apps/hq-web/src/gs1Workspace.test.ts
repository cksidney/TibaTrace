import { describe, expect, it } from 'vitest';

import { validateGtin } from './GS1Workspace.js';

describe('validateGtin', () => {
  it('accepts a valid GTIN-14 and EAN-13 check digit', () => {
    expect(validateGtin('05012345678900')).toBe(true);
    expect(validateGtin('4006381333931')).toBe(true);
  });

  it('rejects malformed lengths and an invalid check digit', () => {
    expect(validateGtin('4006381333932')).toBe(false);
    expect(validateGtin('050123456')).toBe(false);
    expect(validateGtin('0501234567890X')).toBe(false);
  });
});
