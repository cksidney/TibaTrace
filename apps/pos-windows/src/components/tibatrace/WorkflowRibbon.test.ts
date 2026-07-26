import { STAGE_STATUS } from '@dawatrace/shared/design-system/index.js';
import type { WorkflowStageState } from '@dawatrace/shared/design-system/index.js';
import { describe, expect, it } from 'vitest';

import { stageMarker } from './WorkflowRibbon.js';

/**
 * Ribbon stage markers.
 *
 * Only COMPLETE carried a glyph. Every other state fell back to the step
 * number, so BLOCKED, STALE and ACTION_REQUIRED were distinguished from each
 * other -- and from an ordinary pending stage -- by hue alone. The ribbon is
 * the operator's position sense, and a colour-blind operator, a monochrome
 * remote session or a sun-washed screen lost it entirely.
 *
 * Do not relax these to quieten the ribbon. The rule is that a glyph means
 * something needs attention, and it only holds if deviating states have one.
 */

const ALL_STATES = Object.keys(STAGE_STATUS) as readonly WorkflowStageState[];

const DEVIATING: readonly WorkflowStageState[] = ['BLOCKED', 'STALE', 'ACTION_REQUIRED', 'COMPLETE'];
const NEUTRAL: readonly WorkflowStageState[] = ['NOT_STARTED', 'IN_PROGRESS', 'NOT_APPLICABLE'];

describe('stage markers', () => {
  it('covers every stage state the catalogue declares', () => {
    for (const state of ALL_STATES) {
      expect(stageMarker(state, 3).length, `${state} produced no marker`).toBeGreaterThan(0);
    }
  });

  it('marks a deviating stage with a glyph, not its number', () => {
    for (const state of DEVIATING) {
      expect(stageMarker(state, 3), `${state} shows only its step number`).not.toBe('3');
    }
  });

  it('keeps the step number for stages where nothing is wrong', () => {
    // A marker on every stage is noise, and noise is what makes a real marker
    // invisible.
    for (const state of NEUTRAL) {
      expect(stageMarker(state, 7), `${state} should stay neutral`).toBe('7');
    }
  });

  it('distinguishes blocked, stale and action-required from each other', () => {
    const markers = DEVIATING.filter((s) => s !== 'COMPLETE').map((s) => stageMarker(s, 3));
    expect(new Set(markers).size).toBe(markers.length);
  });

  it('never marks a blocked or stale stage with a tick', () => {
    // A tick reads as approval in every context an operator has seen one.
    for (const state of ['BLOCKED', 'STALE', 'ACTION_REQUIRED'] as WorkflowStageState[]) {
      expect(['✓', '✔', '☑']).not.toContain(stageMarker(state, 3));
    }
  });

  it('marks a completed stage distinctly from a blocked one', () => {
    expect(stageMarker('COMPLETE', 3)).not.toBe(stageMarker('BLOCKED', 3));
  });

  it('uses the same glyph vocabulary as the status badges', () => {
    // A symbol must not mean one thing in the ribbon and another in the rail.
    expect(stageMarker('BLOCKED', 3)).toBe(stageMarker('BLOCKED', 9));
    expect(stageMarker('COMPLETE', 1)).toBe(stageMarker('COMPLETE', 8));
  });

  it('renders the step number for a state it does not specially mark', () => {
    expect(stageMarker('NOT_STARTED', 9)).toBe('9');
  });
});
