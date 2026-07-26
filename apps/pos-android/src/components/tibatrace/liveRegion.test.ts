import { CLINICAL_STATUS } from '@dawatrace/shared/design-system/index.js';
import type { ClinicalStatus } from '@dawatrace/shared/design-system/index.js';
import { describe, expect, it } from 'vitest';

import { liveRegionFor } from './liveRegion.js';

/**
 * TalkBack announcement policy.
 *
 * PaymentScreen hardcoded `status === 'BLOCKING' ? 'assertive' : 'polite'`, so
 * PHARMACIST_REVIEW, STALE and ACTION_REQUIRED -- each of which stops the
 * operator and asks something of them -- were queued behind whatever TalkBack
 * was already reading and delivered once the operator went idle.
 *
 * These pin the policy to the shared status metadata rather than to a list a
 * screen maintains by hand. Do not weaken them to quieten the interface.
 */

const ALL_STATUSES = Object.keys(CLINICAL_STATUS) as readonly ClinicalStatus[];

describe('live region policy', () => {
  it('interrupts for every state that demands operator action', () => {
    for (const status of ALL_STATUSES) {
      if (!CLINICAL_STATUS[status].demandsAction) continue;
      expect(liveRegionFor(status), `${status} demands action`).toBe('assertive');
    }
  });

  it('does not interrupt for states that ask nothing', () => {
    for (const status of ALL_STATUSES) {
      if (CLINICAL_STATUS[status].demandsAction) continue;
      expect(liveRegionFor(status), `${status} interrupts needlessly`).not.toBe('assertive');
    }
  });

  it('stays silent for purely informational state', () => {
    // Announcing this is how operators learn to tune announcements out.
    expect(liveRegionFor('INFORMATION')).toBe('none');
  });

  it('covers the statuses a payment notice can carry', () => {
    // The exact set PaymentScreen's notice accepts.
    expect(liveRegionFor('BLOCKING')).toBe('assertive');
    expect(liveRegionFor('ACTION_REQUIRED')).toBe('assertive');
    expect(liveRegionFor('DISABLED')).toBe('none');
  });

  it('returns a value React Native accepts for every status', () => {
    for (const status of ALL_STATUSES) {
      expect(['none', 'polite', 'assertive']).toContain(liveRegionFor(status));
    }
  });
});

describe('parity with the Windows console', () => {
  it('derives politeness from the shared metadata, not a per-screen list', () => {
    // Both platforms read the same field, so a status added on one cannot be
    // announced differently on the other.
    for (const status of ALL_STATUSES) {
      const shared = CLINICAL_STATUS[status].announce;
      const mapped = liveRegionFor(status);
      expect(mapped === 'assertive').toBe(shared === 'assertive');
    }
  });
});
