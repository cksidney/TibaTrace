import { CLINICAL_STATUS } from '@dawatrace/shared/design-system/index.js';
import { describe, expect, it } from 'vitest';

import { deriveHeadline } from './ClinicalRail.js';
import type { ClinicalSummary } from './ClinicalRail.js';

function summary(overrides: Partial<ClinicalSummary> = {}): ClinicalSummary {
  return {
    safeToProceed: true,
    screened: true,
    stale: false,
    blockingCount: 0,
    findings: [],
    connectivity: 'ONLINE',
    ...overrides,
  };
}

describe('clinical headline', () => {
  it('never reports safe without a clinical result', () => {
    const headline = deriveHeadline(null);
    expect(headline.status).not.toBe('SAFE');
    expect(headline.title).toBe('No clinical result');
  });

  it('reports safe only when the server confirmed it', () => {
    expect(deriveHeadline(summary()).status).toBe('SAFE');
  });

  it('does not report safe when the server withheld approval', () => {
    // No findings loaded is not the same as a screening that passed.
    const headline = deriveHeadline(summary({ safeToProceed: false }));
    expect(headline.status).not.toBe('SAFE');
    expect(headline.title).toBe('Progression not permitted');
  });

  it('reports stale ahead of any other state', () => {
    const headline = deriveHeadline(summary({ stale: true, safeToProceed: true }));
    expect(headline.status).toBe('STALE');
    expect(headline.detail).toContain('Re-screening is required');
  });

  it('reports blocked offline dispensing ahead of everything', () => {
    const headline = deriveHeadline(
      summary({ connectivity: 'OFFLINE_DISPENSING_BLOCKED', safeToProceed: true, stale: true }),
    );
    expect(headline.status).toBe('BLOCKING');
    expect(headline.title).toBe('Offline dispensing blocked');
  });

  it('requires screening before payment when none has run', () => {
    const headline = deriveHeadline(summary({ screened: false, safeToProceed: false }));
    expect(headline.title).toBe('Screening required');
  });

  it('names the number of blocking findings', () => {
    expect(deriveHeadline(summary({ blockingCount: 1, safeToProceed: false })).detail).toContain(
      'One blocking finding',
    );
    expect(deriveHeadline(summary({ blockingCount: 3, safeToProceed: false })).detail).toContain(
      '3 blocking findings',
    );
  });

  it('escalates a blocking count above a merely unsafe result', () => {
    const headline = deriveHeadline(summary({ blockingCount: 2, safeToProceed: false }));
    expect(headline.status).toBe('PHARMACIST_REVIEW');
  });
});

describe('status semantics used by the rail', () => {
  it('treats every blocking status as progression-stopping', () => {
    for (const status of ['BLOCKING', 'PHARMACIST_REVIEW', 'STALE', 'ACTION_REQUIRED'] as const) {
      expect(CLINICAL_STATUS[status].blocksProgression).toBe(true);
    }
  });

  it('announces blocking states assertively', () => {
    expect(CLINICAL_STATUS.BLOCKING.announce).toBe('assertive');
    expect(CLINICAL_STATUS.STALE.announce).toBe('assertive');
  });

  it('does not treat information as progression-stopping', () => {
    expect(CLINICAL_STATUS.INFORMATION.blocksProgression).toBe(false);
    expect(CLINICAL_STATUS.SAFE.blocksProgression).toBe(false);
  });
});

/**
 * How the rail headline is announced.
 *
 * The live region was hardcoded aria-live="polite", so a blocking finding, a
 * stale screening or a pharmacist referral was queued behind whatever the
 * screen reader was already saying and delivered when the operator next went
 * idle. At a working till that is after they have already acted.
 *
 * Politeness now follows the status. These tests pin the states that must
 * interrupt; do not relax them to quieten the interface.
 */
describe('headline announcement', () => {
  const announcementFor = (summary: Parameters<typeof deriveHeadline>[0]) =>
    CLINICAL_STATUS[deriveHeadline(summary).status].announce;

  const base = {
    safeToProceed: true,
    screened: true,
    stale: false,
    blockingCount: 0,
    findings: [],
    connectivity: 'ONLINE' as const,
  };

  it('interrupts when dispensing is blocked offline', () => {
    expect(announcementFor({ ...base, connectivity: 'OFFLINE_DISPENSING_BLOCKED' })).toBe(
      'assertive',
    );
  });

  it('interrupts when the screening is stale', () => {
    expect(announcementFor({ ...base, stale: true })).toBe('assertive');
  });

  it('interrupts when a blocking finding is present', () => {
    expect(announcementFor({ ...base, blockingCount: 1 })).toBe('assertive');
  });

  it('interrupts when screening has not been done', () => {
    expect(announcementFor({ ...base, screened: false })).toBe('assertive');
  });

  it('interrupts when the server withheld approval', () => {
    expect(announcementFor({ ...base, safeToProceed: false })).toBe('assertive');
  });

  it('does not interrupt for a safe result', () => {
    // Nothing is being asked of the operator, so nothing should cut in.
    expect(announcementFor(base)).not.toBe('assertive');
  });

  it('announces every headline a blocked state can produce assertively', () => {
    // Catches a future headline branch that returns a blocking status without
    // its announcement being reconsidered.
    const blockedInputs = [
      { ...base, connectivity: 'OFFLINE_DISPENSING_BLOCKED' as const },
      { ...base, stale: true },
      { ...base, blockingCount: 3 },
      { ...base, screened: false },
      { ...base, safeToProceed: false },
    ];
    for (const input of blockedInputs) {
      const status = deriveHeadline(input).status;
      expect(CLINICAL_STATUS[status].demandsAction, `${status} should demand action`).toBe(true);
      expect(CLINICAL_STATUS[status].announce).toBe('assertive');
    }
  });
});
