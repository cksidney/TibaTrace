import { describe, expect, it } from 'vitest';

import { deriveRetailPrimaryAction } from './retail.js';

describe('deriveRetailPrimaryAction', () => {
  it('does not present settlement as complete after a basket is prepared', () => {
    expect(
      deriveRetailPrimaryAction({ state: 'READY_FOR_PAYMENT', lineCount: 2, hasStore: true }),
    ).toEqual({
      kind: 'NONE',
      label: 'Settlement required',
      detail: 'Retail settlement is not available in this POS pilot.',
      enabled: false,
    });
  });

  it('offers one explicit action for a populated draft', () => {
    expect(
      deriveRetailPrimaryAction({ state: 'DRAFT', lineCount: 1, hasStore: true }),
    ).toMatchObject({ kind: 'PREPARE_PAYMENT', label: 'Prepare payment', enabled: true });
  });
});
