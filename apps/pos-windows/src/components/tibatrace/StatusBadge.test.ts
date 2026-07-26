import { CLINICAL_STATUS } from '@dawatrace/shared/design-system/index.js';
import type { ClinicalStatus } from '@dawatrace/shared/design-system/index.js';
import { describe, expect, it } from 'vitest';

import { glyphFor } from './StatusBadge.js';

/**
 * The badge's guarantee is that a status survives losing its colour: a
 * colour-blind operator, a sun-washed till screen, a monochrome remote session.
 * That guarantee is only real if the glyph carries the distinction on its own.
 *
 * These tests exist because it did not. `user-check` (PHARMACIST_REVIEW, which
 * blocks progression) rendered the same '✓' as `shield-check` (SAFE), so in
 * monochrome a state requiring a pharmacist looked like approval.
 *
 * Do not relax these to make adding a status easier. A new status without a
 * glyph is the failure being prevented, not an inconvenience.
 */

const ALL_STATUSES = Object.keys(CLINICAL_STATUS) as readonly ClinicalStatus[];

const blocking = ALL_STATUSES.filter((s) => CLINICAL_STATUS[s].blocksProgression);
const permitting = ALL_STATUSES.filter((s) => !CLINICAL_STATUS[s].blocksProgression);

describe('glyph coverage', () => {
  it('covers every status', () => {
    // The '•' fallback is indistinguishable across statuses. A status that hits
    // it has silently lost the non-colour signal entirely.
    for (const status of ALL_STATUSES) {
      expect(glyphFor(status), `${status} fell back to the placeholder glyph`).not.toBe('•');
    }
  });

  it('covers the statuses the catalogue actually declares', () => {
    expect(ALL_STATUSES.length).toBeGreaterThan(0);
    expect(blocking.length).toBeGreaterThan(0);
    expect(permitting.length).toBeGreaterThan(0);
  });
});

describe('blocking states are distinguishable without colour', () => {
  it('shares no glyph between a blocking and a permitting status', () => {
    const permittingGlyphs = new Set(permitting.map(glyphFor));

    for (const status of blocking) {
      expect(
        permittingGlyphs.has(glyphFor(status)),
        `${status} blocks progression but renders '${glyphFor(status)}', which a permitting status also uses`,
      ).toBe(false);
    }
  });

  it('gives each blocking status its own glyph', () => {
    // Blocking states demand different responses -- an unresolved interaction
    // is not a stale context is not a pharmacist referral.
    const seen = new Map<string, ClinicalStatus>();
    for (const status of blocking) {
      const glyph = glyphFor(status);
      const previous = seen.get(glyph);
      expect(previous, `${status} and ${previous} both render '${glyph}'`).toBeUndefined();
      seen.set(glyph, status);
    }
  });

  it('never marks a blocking status with a tick', () => {
    // A tick reads as approval in every context an operator has ever seen one.
    for (const status of blocking) {
      expect(['✓', '✔', '☑'], `${status} blocks progression but renders a tick`).not.toContain(
        glyphFor(status),
      );
    }
  });

  it('specifically distinguishes pharmacist review from safe', () => {
    // The regression this file was written for.
    expect(glyphFor('PHARMACIST_REVIEW')).not.toBe(glyphFor('SAFE'));
    expect(glyphFor('PHARMACIST_REVIEW')).not.toBe(glyphFor('COMPLETED'));
  });
});

describe('status metadata', () => {
  it('gives every status a label, so colour is never the only signal', () => {
    for (const status of ALL_STATUSES) {
      expect(CLINICAL_STATUS[status].label.trim().length).toBeGreaterThan(0);
    }
  });

  it('announces assertively wherever the operator must act', () => {
    // A demand discovered by exploration is a demand discovered too late.
    // ACTION_REQUIRED was 'polite', which waits for an idle moment a busy till
    // never has.
    for (const status of ALL_STATUSES) {
      if (!CLINICAL_STATUS[status].demandsAction) continue;
      expect(CLINICAL_STATUS[status].announce, `${status} demands action but is not assertive`).toBe(
        'assertive',
      );
    }
  });

  it('does not interrupt for states that ask nothing of the operator', () => {
    // PROCESSING resolves itself; DISABLED is a passive absence. Announcing
    // them assertively would train operators to ignore the interruptions that
    // do matter.
    for (const status of ALL_STATUSES) {
      if (CLINICAL_STATUS[status].demandsAction) continue;
      expect(CLINICAL_STATUS[status].announce, `${status} interrupts without asking anything`).not.toBe(
        'assertive',
      );
    }
  });

  it('never demands action in a state that permits progression', () => {
    // Otherwise the operator is told to act while nothing stops them, and the
    // demand becomes advisory in practice.
    for (const status of ALL_STATUSES) {
      if (!CLINICAL_STATUS[status].demandsAction) continue;
      expect(CLINICAL_STATUS[status].blocksProgression, `${status} demands action but permits progression`).toBe(true);
    }
  });
});
