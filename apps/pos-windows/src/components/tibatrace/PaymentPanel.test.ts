import type { PaymentState } from '@dawatrace/shared/dispensing/index.js';
import { paymentPermitsSupply } from '@dawatrace/shared/dispensing/index.js';
import { describe, expect, it } from 'vitest';

import { TENDER_OPTIONS } from '@dawatrace/shared/dispensing/index.js';

import { paymentActionState, paymentStatusMeta, remainingAmount } from './PaymentPanel.js';
import { lineStatus } from './PrescriptionWorkspace.js';

/**
 * Money arithmetic on the panel.
 *
 * The remaining balance was computed with `Number(amountDue) - Number(settled)`
 * and rendered straight through `.toFixed(2)`, so any amount the server did not
 * send as a plain decimal string put "NaN" on a money field at the till.
 *
 * The rule these pin down is that an amount we cannot read is unknown, never
 * zero. Zero asserts that nothing is owed. Do not relax these to accept a
 * fallback value.
 */
describe('remaining balance', () => {
  it('subtracts settled from due', () => {
    expect(remainingAmount('1250.00', '500.00')).toBe(750);
    expect(remainingAmount('1250.00', '0.00')).toBe(1250);
    expect(remainingAmount('1250.00', '1250.00')).toBe(0);
  });

  it('reports unknown rather than NaN for a grouped amount', () => {
    expect(remainingAmount('1,250.00', '0.00')).toBeNull();
    expect(remainingAmount('1250.00', '1,000.00')).toBeNull();
  });

  it('never silently under-reports a grouped amount the way parseFloat would', () => {
    // parseFloat('1,250,000.00') is 1250 -- plausible on screen, wrong by a
    // factor of a thousand.
    expect(remainingAmount('1,250,000.00', '0.00')).toBeNull();
  });

  it('reports unknown, not zero, for an unreadable amount', () => {
    for (const bad of ['', '   ', 'abc', 'KES 1250', '1250.00.00', '1e3', 'NaN', 'Infinity']) {
      expect(remainingAmount(bad, '0.00'), `${bad} was parsed`).toBeNull();
      expect(remainingAmount('1250.00', bad), `${bad} was parsed`).toBeNull();
    }
  });

  it('reports unknown when either amount is absent', () => {
    expect(remainingAmount(null, '0.00')).toBeNull();
    expect(remainingAmount('1250.00', null)).toBeNull();
    expect(remainingAmount(null, null)).toBeNull();
  });

  it('handles an overpayment without clamping it away', () => {
    // A negative remaining is real information: it means a refund is owed.
    expect(remainingAmount('1000.00', '1250.00')).toBe(-250);
  });

  it('accepts the decimal shapes DRF actually emits', () => {
    expect(remainingAmount('1250', '0')).toBe(1250);
    expect(remainingAmount('1250.5', '0.25')).toBeCloseTo(1250.25, 2);
  });
});

describe('tender availability', () => {
  it('only offers tenders whose settlement path exists on the server', () => {
    // Offering a tender the server cannot settle lets an operator start a
    // payment the system cannot finish. SPLIT is excluded here because it is an
    // allocation mode across the settleable tenders, not a tender itself.
    const settleable = TENDER_OPTIONS.filter((o) => o.available && o.type !== 'SPLIT').map(
      (o) => o.type,
    );
    expect(settleable).toEqual(['CASH', 'CARD']);
  });

  it('keeps MPESA disabled until a real provider adapter exists', () => {
    const mpesa = TENDER_OPTIONS.find((o) => o.type === 'MPESA');
    expect(mpesa?.available).toBe(false);
    expect(mpesa?.blocker).toBeTruthy();
  });

  it('states why an unavailable tender is disabled', () => {
    for (const option of TENDER_OPTIONS.filter((o) => !o.available)) {
      expect(option.blocker, `${option.type} needs a stated blocker`).toBeTruthy();
    }
  });

  it('labels card as manual approval rather than terminal integration', () => {
    const card = TENDER_OPTIONS.find((o) => o.type === 'CARD');
    expect(card?.label.toLowerCase()).toContain('manual');
  });
});

describe('payment status presentation', () => {
  it('never presents partial payment as complete', () => {
    const meta = paymentStatusMeta('PARTIALLY_PAID');
    expect(meta.status).toBe('ACTION_REQUIRED');
    expect(meta.label).toBe('Partially paid');
    expect(paymentPermitsSupply('PARTIALLY_PAID')).toBe(false);
  });

  it.each<PaymentState>(['FAILED', 'CANCELLED', 'REVERSED'])(
    'presents %s as blocking',
    (state) => {
      expect(paymentStatusMeta(state).status).toBe('BLOCKING');
    },
  );

  it('presents a pending reversal distinctly from a completed one', () => {
    expect(paymentStatusMeta('REVERSAL_PENDING').status).toBe('STALE');
    expect(paymentStatusMeta('REVERSED').status).toBe('BLOCKING');
  });

  it('marks only genuinely settled states as complete or benign', () => {
    expect(paymentStatusMeta('PAID').status).toBe('COMPLETED');
    for (const state of ['NOT_REQUIRED', 'WAIVED'] as PaymentState[]) {
      expect(paymentStatusMeta(state).status).toBe('INFORMATION');
      expect(paymentPermitsSupply(state)).toBe(true);
    }
  });
});

describe('medicine line presentation', () => {
  it('does not present an unrecognised server state as fine', () => {
    const state = lineStatus('SOME_FUTURE_STATE');
    expect(state.status).toBe('ACTION_REQUIRED');
  });

  it('distinguishes prepared from final-checked from supplied', () => {
    expect(lineStatus('PREPARED').status).toBe('INFORMATION');
    expect(lineStatus('CHECKED').status).toBe('SAFE');
    expect(lineStatus('SUPPLIED').status).toBe('COMPLETED');
  });

  it('presents a reversed line as blocking', () => {
    expect(lineStatus('REVERSED').status).toBe('BLOCKING');
  });
});

/**
 * The collect action gate.
 *
 * `disabled`, the button fill and the cursor were three separate expressions
 * and they disagreed. The fill ignored `priced` and the selected tender, so the
 * button rendered green and inviting while doing nothing when pressed.
 *
 * These tests pin the gate itself rather than the styling, so the three can
 * never drift apart again. Do not weaken them to allow a payment through a
 * state the panel cannot account for.
 */
describe('collect action gate', () => {
  const ready = {
    priced: true,
    remaining: 1250,
    keyedAmount: '1250.00',
    canTakePayment: true,
    tenderAvailable: true,
    busy: false,
    submitted: false,
  };

  it('offers the action when everything is in order', () => {
    expect(paymentActionState(ready).enabled).toBe(true);
    expect(paymentActionState(ready).reason).toBe('');
  });

  it('refuses when the amount could not be read', () => {
    // The panel must not invite a hand-keyed amount to paper over an amount it
    // could not parse.
    const state = paymentActionState({ ...ready, remaining: null });
    expect(state.enabled).toBe(false);
    expect(state.reason).toContain('could not be read');
  });

  it('refuses a hand-keyed amount that is not a plain number', () => {
    for (const keyed of ['1,250.00', 'KES 1250', '', 'abc', '1e3']) {
      expect(paymentActionState({ ...ready, keyedAmount: keyed }).enabled, keyed).toBe(false);
    }
  });

  it('refuses without an open intent', () => {
    expect(paymentActionState({ ...ready, priced: false }).enabled).toBe(false);
  });

  it('refuses a tender with no settlement path', () => {
    expect(paymentActionState({ ...ready, tenderAvailable: false }).enabled).toBe(false);
  });

  it('refuses while a payment is in flight, so a second click is not a second charge', () => {
    expect(paymentActionState({ ...ready, busy: true }).enabled).toBe(false);
    expect(paymentActionState({ ...ready, submitted: true }).enabled).toBe(false);
  });

  it('refuses when the clinical state does not permit payment', () => {
    expect(paymentActionState({ ...ready, canTakePayment: false }).enabled).toBe(false);
  });

  it('always states a reason when it refuses', () => {
    // A disabled control with no explanation reads as a broken screen.
    const refusals = [
      { ...ready, priced: false },
      { ...ready, remaining: null },
      { ...ready, keyedAmount: 'abc' },
      { ...ready, tenderAvailable: false },
      { ...ready, canTakePayment: false },
      { ...ready, busy: true },
    ];
    for (const input of refusals) {
      const state = paymentActionState(input);
      expect(state.enabled).toBe(false);
      expect(state.reason.trim().length, JSON.stringify(input)).toBeGreaterThan(0);
    }
  });
});
