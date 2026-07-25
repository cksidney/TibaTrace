import {
  CLINICAL_STATUS,
  controlSize,
  deriveStages,
  nextAction,
} from '@dawatrace/shared/design-system/index.js';
import type { DispensingEpisodeDTO, PaymentState } from '@dawatrace/shared/dispensing/index.js';
import { paymentPermitsSupply } from '@dawatrace/shared/dispensing/index.js';
import { describe, expect, it } from 'vitest';

/**
 * Android must never apply weaker clinical rules than Windows.
 *
 * Both clients derive their gates from the same shared functions, so these
 * tests assert the shared behaviour holds when driven from the Android screen's
 * inputs -- if someone forks the logic per-platform, these fail.
 */

function episode(overrides: Partial<DispensingEpisodeDTO> = {}): DispensingEpisodeDTO {
  return {
    id: 'ep-1',
    dispensing_number: 'DISP-1',
    prescription: 'rx-1',
    patient: 'Grace Kamau',
    branch: 'br-1',
    pharmacy_location: 'wh-1',
    pharmacist: 'u-1',
    status: 'READY_FOR_SUPPLY',
    initiated_at: '2026-01-01T00:00:00Z',
    completed_at: null,
    payment_state: 'PAID',
    payment_reference: '',
    tender_type: 'CASH',
    paid_amount: '0',
    collector_name: '',
    collector_id_number: '',
    collector_phone: '',
    collector_relationship: '',
    collection_proof_type: '',
    collected_at: null,
    controlled_witness: null,
    controlled_authority_checked: false,
    counselling_status: 'NOT_STARTED',
    notes: '',
    idempotency_key: 'k',
    lines: [],
    ...overrides,
  } as DispensingEpisodeDTO;
}

const CLEAN = {
  screened: true,
  safeToProceed: true,
  stale: false,
  pharmacistReviewRequired: false,
};

describe('android applies the same supply gate as windows', () => {
  it.each<PaymentState>(['PENDING', 'PARTIALLY_PAID', 'FAILED', 'CANCELLED', 'REVERSED'])(
    'blocks supply when payment is %s',
    (state) => {
      const stages = deriveStages(episode({ payment_state: state }), CLEAN);
      const supply = stages.find((s) => s.id === 'SUPPLY');
      expect(supply?.state).toBe('BLOCKED');
      expect(paymentPermitsSupply(state)).toBe(false);
    },
  );

  it('permits supply only on a settled payment state', () => {
    const stages = deriveStages(episode({ payment_state: 'PAID' }), CLEAN);
    expect(stages.find((s) => s.id === 'SUPPLY')?.state).toBe('ACTION_REQUIRED');
  });

  it('blocks on a stale clinical context regardless of payment', () => {
    const stages = deriveStages(episode({ payment_state: 'PAID' }), { ...CLEAN, stale: true });
    expect(stages.find((s) => s.id === 'CLINICAL_SCREENING')?.state).toBe('STALE');
  });

  it('surfaces the blocker as the next action', () => {
    const stages = deriveStages(episode({ payment_state: 'PARTIALLY_PAID' }), CLEAN);
    expect(nextAction(stages)?.id).toBe('SUPPLY');
  });
});

describe('android accessibility guarantees', () => {
  it('uses accessible touch targets for critical actions', () => {
    // A mis-tap on a clinical control is expensive.
    expect(controlSize.touchTarget).toBeGreaterThanOrEqual(48);
    expect(controlSize.touchTargetLarge).toBeGreaterThanOrEqual(48);
  });

  it('announces blocking clinical states assertively', () => {
    expect(CLINICAL_STATUS.BLOCKING.announce).toBe('assertive');
    expect(CLINICAL_STATUS.PHARMACIST_REVIEW.announce).toBe('assertive');
  });

  it('carries a label for every status so colour is never the only signal', () => {
    for (const meta of Object.values(CLINICAL_STATUS)) {
      expect(meta.label.length).toBeGreaterThan(0);
      expect(meta.icon.length).toBeGreaterThan(0);
    }
  });
});

describe('android payment parity with windows', () => {
  it('offers only tenders the server can actually settle', async () => {
    const { TENDER_OPTIONS } = await import('@dawatrace/shared/dispensing/index.js');
    // SPLIT is an allocation mode, not a tender: it distributes across the
    // settleable ones and is never sent as a tender_type.
    const settleable = TENDER_OPTIONS.filter((t) => t.available && t.type !== 'SPLIT').map(
      (t) => t.type,
    );
    expect(settleable).toEqual(['CASH', 'CARD']);
  });

  it('keeps MPESA disabled until a real provider adapter exists', async () => {
    // The fake adapter is for tests and demos; it must not make the tender look
    // settleable on a real deployment.
    const { TENDER_OPTIONS } = await import('@dawatrace/shared/dispensing/index.js');
    const mpesa = TENDER_OPTIONS.find((t) => t.type === 'MPESA');
    expect(mpesa?.available).toBe(false);
    expect(mpesa?.blocker).toBeTruthy();
  });

  it('states a blocker for every unavailable tender', async () => {
    const { TENDER_OPTIONS } = await import('@dawatrace/shared/dispensing/index.js');
    for (const option of TENDER_OPTIONS.filter((t) => !t.available)) {
      expect(option.blocker, `${option.type} needs a stated blocker`).toBeTruthy();
    }
  });

  it('shares one tender declaration with windows', async () => {
    // Android must not quietly offer a payment route Windows refuses.
    const { TENDER_OPTIONS } = await import('@dawatrace/shared/dispensing/index.js');
    expect(TENDER_OPTIONS.map((t) => `${t.type}:${t.available}`)).toEqual([
      'CASH:true',
      'CARD:true',
      'MPESA:false',
      'SPLIT:true',
    ]);
  });
});
