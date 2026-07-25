import type { PaymentState } from '@dawatrace/shared/dispensing/index.js';
import { paymentPermitsSupply } from '@dawatrace/shared/dispensing/index.js';
import { describe, expect, it } from 'vitest';

import { TENDER_OPTIONS } from '@dawatrace/shared/dispensing/index.js';

import { paymentStatusMeta } from './PaymentPanel.js';
import { lineStatus } from './PrescriptionWorkspace.js';

describe('tender availability', () => {
  it('only offers tenders whose settlement path exists on the server', () => {
    // Offering a tender the server cannot settle lets an operator start a
    // payment the system cannot finish.
    const available = TENDER_OPTIONS.filter((option) => option.available).map((o) => o.type);
    expect(available).toEqual(['CASH', 'CARD']);
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
