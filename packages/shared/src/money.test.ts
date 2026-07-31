import { describe, expect, it } from 'vitest';

import { formatDecimal, formatMoney } from './money.js';

describe('formatDecimal', () => {
  it('pads to two places', () => {
    expect(formatDecimal('150')).toBe('150.00');
    expect(formatDecimal('150.1')).toBe('150.10');
  });

  it('rounds half up', () => {
    expect(formatDecimal('10.005')).toBe('10.01');
    expect(formatDecimal('10.004')).toBe('10.00');
    expect(formatDecimal('1.999')).toBe('2.00');
  });
});

describe('formatMoney', () => {
  it('groups thousands and keeps two places', () => {
    expect(formatMoney('3000')).toBe('KES 3,000.00');
    expect(formatMoney('-50.5')).toBe('KES -50.50');
  });
});
