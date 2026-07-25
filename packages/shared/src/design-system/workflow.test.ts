import { describe, expect, it } from 'vitest';

import type { DispensingEpisodeDTO, PaymentState } from '../dispensing/types.js';
import { dominantStatus, ALLERGY_STATUS } from './clinicalStatus.js';
import { deriveStages, nextAction } from './workflow.js';

function episode(overrides: Partial<DispensingEpisodeDTO> = {}): DispensingEpisodeDTO {
  return {
    id: 'ep-1',
    dispensing_number: 'DISP-1',
    prescription: 'rx-1',
    patient: 'pat-1',
    branch: 'br-1',
    pharmacy_location: 'wh-1',
    pharmacist: 'u-1',
    status: 'PREPARING',
    initiated_at: '2026-01-01T00:00:00Z',
    completed_at: null,
    payment_state: 'PENDING',
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

function stage(stages: readonly ReturnType<typeof deriveStages>[number][], id: string) {
  const found = stages.find((s) => s.id === id);
  if (!found) throw new Error(`missing stage ${id}`);
  return found;
}

describe('workflow ribbon', () => {
  it('shows nothing started without an episode', () => {
    const stages = deriveStages(null);
    expect(stages.every((s) => s.state === 'NOT_STARTED')).toBe(true);
  });

  it('marks supply blocked while payment is only partial', () => {
    // Visiting a screen must never imply completion, and part-payment must
    // never present supply as available.
    const stages = deriveStages(
      episode({ status: 'READY_FOR_SUPPLY', payment_state: 'PARTIALLY_PAID' }),
    );
    expect(stage(stages, 'SUPPLY').state).toBe('BLOCKED');
    expect(stage(stages, 'SUPPLY').blockedReason).toContain('payment is settled');
    expect(stage(stages, 'PAYMENT').blockedReason).toContain('balance must be settled');
  });

  it.each<PaymentState>(['PENDING', 'FAILED', 'CANCELLED', 'REVERSED'])(
    'blocks supply when payment is %s',
    (state) => {
      const stages = deriveStages(episode({ status: 'READY_FOR_SUPPLY', payment_state: state }));
      expect(stage(stages, 'SUPPLY').state).toBe('BLOCKED');
    },
  );

  it('permits supply once payment is settled', () => {
    const stages = deriveStages(episode({ status: 'READY_FOR_SUPPLY', payment_state: 'PAID' }));
    expect(stage(stages, 'SUPPLY').state).toBe('ACTION_REQUIRED');
  });

  it('treats a waived payment as not applicable rather than complete', () => {
    const stages = deriveStages(episode({ status: 'READY_FOR_SUPPLY', payment_state: 'WAIVED' }));
    expect(stage(stages, 'PAYMENT').state).toBe('NOT_APPLICABLE');
    expect(stage(stages, 'SUPPLY').state).toBe('ACTION_REQUIRED');
  });

  it('marks screening stale when the basket changed after approval', () => {
    const stages = deriveStages(episode(), {
      screened: true,
      safeToProceed: true,
      stale: true,
      pharmacistReviewRequired: false,
    });
    const screening = stage(stages, 'CLINICAL_SCREENING');
    expect(screening.state).toBe('STALE');
    expect(screening.blockedReason).toContain('Re-screening is required');
  });

  it('blocks screening when a pharmacist decision is outstanding', () => {
    const stages = deriveStages(episode(), {
      screened: true,
      safeToProceed: false,
      stale: false,
      pharmacistReviewRequired: true,
    });
    expect(stage(stages, 'CLINICAL_SCREENING').state).toBe('BLOCKED');
  });

  it('never marks an unstarted stage navigable', () => {
    const stages = deriveStages(null);
    expect(stages.some((s) => s.navigable)).toBe(false);
  });

  it('surfaces the blocker as the next action ahead of lesser stages', () => {
    const stages = deriveStages(
      episode({ status: 'READY_FOR_SUPPLY', payment_state: 'PARTIALLY_PAID' }),
    );
    expect(nextAction(stages)?.id).toBe('SUPPLY');
  });

  it('marks collection complete only once the server recorded it', () => {
    const uncollected = deriveStages(episode({ status: 'SUPPLIED' }));
    expect(stage(uncollected, 'COLLECTION').state).toBe('ACTION_REQUIRED');

    const collected = deriveStages(
      episode({ status: 'SUPPLIED', collected_at: '2026-01-01T10:00:00Z' }),
    );
    expect(stage(collected, 'COLLECTION').state).toBe('COMPLETE');
  });
});

describe('status semantics', () => {
  it('surfaces the most severe status in a summary', () => {
    expect(dominantStatus(['INFORMATION', 'BLOCKING', 'SAFE'])).toBe('BLOCKING');
    expect(dominantStatus(['SAFE', 'INFORMATION'])).toBe('INFORMATION');
  });

  it('does not present unknown allergy status as safe', () => {
    // Absence of recorded allergies is not evidence of absence.
    expect(ALLERGY_STATUS.UNKNOWN.status).not.toBe('SAFE');
    expect(ALLERGY_STATUS.NONE_KNOWN.status).toBe('SAFE');
    expect(ALLERGY_STATUS.UNKNOWN.label).toContain('unknown');
  });
});
