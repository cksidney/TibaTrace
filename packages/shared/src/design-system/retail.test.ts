import { describe, expect, it } from 'vitest';

import { deriveRetailPrimaryAction } from './retail.js';

describe('deriveRetailPrimaryAction', () => {
  it('offers cash settlement after a basket is prepared without enabling other tenders', () => {
    expect(
      deriveRetailPrimaryAction({ state: 'READY_FOR_PAYMENT', lineCount: 2, hasStore: true }),
    ).toEqual({
      kind: 'SETTLE_CASH',
      label: 'Settle cash payment',
      detail: 'Cash only. Card and M-PESA settlement remain unavailable.',
      enabled: true,
    });
  });

  it('offers one explicit action for a populated draft', () => {
    expect(
      deriveRetailPrimaryAction({ state: 'DRAFT', lineCount: 1, hasStore: true }),
    ).toMatchObject({ kind: 'PREPARE_PAYMENT', label: 'Prepare payment', enabled: true });
  });

  it('allows a fresh basket after the previous sale has completed', () => {
    expect(
      deriveRetailPrimaryAction({ state: 'COMPLETED', lineCount: 1, hasStore: true }),
    ).toMatchObject({ kind: 'START_SALE', label: 'Start new sale', enabled: true });
  });
});
