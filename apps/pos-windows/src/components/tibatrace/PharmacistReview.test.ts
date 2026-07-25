import { describe, expect, it } from 'vitest';

import { DECISIONS } from './PharmacistReview.js';

describe('pharmacist decision vocabulary', () => {
  it('offers the four decisions the backend recognises', () => {
    expect(DECISIONS.map((d) => d.value)).toEqual([
      'APPROVE_AS_WRITTEN',
      'APPROVE_WITH_COUNSELLING',
      'REQUEST_CLARIFICATION',
      'REJECT_SUPPLY',
    ]);
  });

  it('states the consequence of every decision before submission', () => {
    // An operator must know what a decision does while choosing it, not after.
    for (const decision of DECISIONS) {
      expect(decision.consequence.length, `${decision.value} needs a consequence`).toBeGreaterThan(
        20,
      );
    }
  });

  it('warns that approval is bound to the current context', () => {
    const approve = DECISIONS.find((d) => d.value === 'APPROVE_AS_WRITTEN');
    expect(approve?.consequence).toMatch(/current clinical context/i);
    expect(approve?.consequence).toMatch(/invalidates/i);
  });

  it('makes clear that a rejection blocks progression', () => {
    const reject = DECISIONS.find((d) => d.value === 'REJECT_SUPPLY');
    expect(reject?.consequence).toMatch(/cannot progress|refuses supply/i);
  });

  it('uses deliberate clinical language rather than dismissive phrasing', () => {
    // "Continue anyway" frames an override as brushing past an inconvenience.
    const wording = DECISIONS.map((d) => `${d.label} ${d.consequence}`).join(' ').toLowerCase();
    expect(wording).not.toContain('continue anyway');
    expect(wording).not.toContain('are you sure');
    expect(wording).not.toContain('oops');
    expect(wording).not.toContain('something went wrong');
  });
});
