import { describe, expect, it } from 'vitest';

import type { TenderLine } from './splitTender.js';
import { summarise, validateAllocation } from './splitTender.js';

function line(overrides: Partial<TenderLine> = {}): TenderLine {
  return {
    id: 't-1',
    tenderType: 'CASH',
    allocated: 0,
    settled: 0,
    status: 'ALLOCATED',
    ...overrides,
  };
}

describe('allocated is not settled', () => {
  it('does not count an allocated tender as money collected', () => {
    // Keying in a tender is a plan, not a payment.
    const summary = summarise(1000, [line({ allocated: 1000 })]);
    expect(summary.allocated).toBe(1000);
    expect(summary.settled).toBe(0);
    expect(summary.fullySettled).toBe(false);
    expect(summary.remaining).toBe(1000);
  });

  it('does not count a pending provider tender as settled', () => {
    // Otherwise the till shows a completed sale while the customer has not yet
    // approved anything on their handset.
    const summary = summarise(1000, [
      line({ tenderType: 'MPESA', allocated: 1000, status: 'PENDING' }),
    ]);
    expect(summary.settled).toBe(0);
    expect(summary.pending).toBe(1000);
    expect(summary.fullySettled).toBe(false);
  });

  it('reports fully settled only when settled value covers the amount due', () => {
    const summary = summarise(1000, [
      line({ allocated: 400, settled: 400, status: 'SETTLED' }),
      line({ id: 't-2', tenderType: 'CARD', allocated: 600, settled: 600, status: 'SETTLED' }),
    ]);
    expect(summary.fullySettled).toBe(true);
    expect(summary.remaining).toBe(0);
  });
});

describe('failed and cancelled components', () => {
  it('excludes a cancelled tender from allocation', () => {
    const summary = summarise(1000, [
      line({ allocated: 400, settled: 400, status: 'SETTLED' }),
      line({ id: 't-2', allocated: 600, status: 'CANCELLED' }),
    ]);
    expect(summary.allocated).toBe(400);
    expect(summary.unallocated).toBe(600);
  });

  it('keeps settled value when another component fails', () => {
    const summary = summarise(1000, [
      line({ allocated: 400, settled: 400, status: 'SETTLED' }),
      line({ id: 't-2', tenderType: 'MPESA', allocated: 600, status: 'FAILED' }),
    ]);
    expect(summary.settled).toBe(400);
    expect(summary.failed).toBe(600);
    expect(summary.unallocated).toBe(600);
  });
});

describe('allocation validation', () => {
  it('refuses an allocation that exceeds the amount due', () => {
    // Rejects rather than clamps: silently reducing the figure would leave the
    // operator believing they collected more than the record shows.
    const error = validateAllocation(1000, [line({ allocated: 600 })], {
      amount: 500,
      tenderType: 'CASH',
      available: true,
    });
    expect(error).toBe('EXCEEDS_AMOUNT_DUE');
  });

  it('refuses a zero or negative allocation', () => {
    expect(
      validateAllocation(1000, [], { amount: 0, tenderType: 'CASH', available: true }),
    ).toBe('NOT_POSITIVE');
    expect(
      validateAllocation(1000, [], { amount: -50, tenderType: 'CASH', available: true }),
    ).toBe('NOT_POSITIVE');
  });

  it('refuses a tender the deployment cannot settle', () => {
    expect(
      validateAllocation(1000, [], { amount: 500, tenderType: 'MPESA', available: false }),
    ).toBe('TENDER_UNAVAILABLE');
  });

  it('refuses another line once the full amount is allocated', () => {
    const error = validateAllocation(1000, [line({ allocated: 1000 })], {
      amount: 50,
      tenderType: 'CASH',
      available: true,
    });
    expect(error).toBe('NOTHING_OUTSTANDING');
  });

  it('permits an allocation that exactly fills the balance', () => {
    expect(
      validateAllocation(1000, [line({ allocated: 400 })], {
        amount: 600,
        tenderType: 'CARD',
        available: true,
      }),
    ).toBeNull();
  });
});

describe('change', () => {
  it('gives change only from over-tendered cash', () => {
    const summary = summarise(1000, [line({ allocated: 1000, settled: 1000, status: 'SETTLED' })], 1200);
    expect(summary.changeDue).toBe(200);
  });

  it('never gives change against a card or provider tender', () => {
    // Those cannot hand cash back.
    const summary = summarise(
      1000,
      [line({ tenderType: 'CARD', allocated: 1000, settled: 1000, status: 'SETTLED' })],
      1200,
    );
    expect(summary.changeDue).toBe(1200);
    const noCash = summarise(
      1000,
      [line({ tenderType: 'CARD', allocated: 1000, settled: 1000, status: 'SETTLED' })],
      0,
    );
    expect(noCash.changeDue).toBe(0);
  });
});

describe('three-way split', () => {
  it('tracks a cash, card and provider allocation through settlement', () => {
    const lines: TenderLine[] = [
      line({ id: 'a', tenderType: 'CASH', allocated: 200, settled: 200, status: 'SETTLED' }),
      line({ id: 'b', tenderType: 'CARD', allocated: 300, settled: 300, status: 'SETTLED' }),
      line({ id: 'c', tenderType: 'MPESA', allocated: 500, settled: 0, status: 'PENDING' }),
    ];
    const summary = summarise(1000, lines);
    expect(summary.fullyAllocated).toBe(true);
    expect(summary.settled).toBe(500);
    expect(summary.pending).toBe(500);
    // Not settled while the provider leg is outstanding.
    expect(summary.fullySettled).toBe(false);
    expect(summary.remaining).toBe(500);
  });

  it('rounds to cents so display never drifts', () => {
    const summary = summarise(
      100.03,
      [
        line({ id: 'a', allocated: 33.34, settled: 33.34, status: 'SETTLED' }),
        line({ id: 'b', allocated: 33.34, settled: 33.34, status: 'SETTLED' }),
        line({ id: 'c', allocated: 33.35, settled: 33.35, status: 'SETTLED' }),
      ],
    );
    expect(summary.settled).toBe(100.03);
    expect(summary.remaining).toBe(0);
    expect(summary.fullySettled).toBe(true);
  });
});
