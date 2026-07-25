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
