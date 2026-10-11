import { describe, expect, it } from 'vitest';

import { retailCashChangeDue } from './cash.js';

describe('retailCashChangeDue', () => {
  it('calculates exact change without floating point drift', () => {
    expect(retailCashChangeDue('125.35', '200.00')).toBe('74.65');
    expect(retailCashChangeDue('125.35', '125.35')).toBe('0.00');
  });

  it('blocks short or malformed cash amounts', () => {
    expect(retailCashChangeDue('125.35', '125.34')).toBeNull();
    expect(retailCashChangeDue('125.35', 'cash')).toBeNull();
    expect(retailCashChangeDue('125.35', '-1.00')).toBeNull();
    expect(retailCashChangeDue('125.35', '125.351')).toBeNull();
  });
});
