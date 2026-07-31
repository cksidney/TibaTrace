/**
 * Non-colour status markers shared by Windows and Android POS.
 *
 * Colour alone is never enough on a till screen. These glyphs must stay unique
 * across blocking vs non-blocking states -- StatusBadge tests enforce that on
 * Windows, and Android StageRow uses the same map so the two clients cannot
 * diverge.
 */
import { CLINICAL_STATUS } from './clinicalStatus.js';
import type { ClinicalStatus } from './clinicalStatus.js';
import type { WorkflowStageState } from './workflow.js';

const GLYPH: Record<string, string> = {
  'octagon-x': '✕',
  // A flag, not a tick: someone must still look at this.
  'user-check': '⚑',
  history: '↺',
  'cloud-off': '⌁',
  'alert-triangle': '!',
  loader: '◌',
  info: 'i',
  'check-circle': '✓',
  'shield-check': '✓',
  lock: '🔒',
};

/** The glyph a clinical status renders. */
export function glyphFor(status: ClinicalStatus): string {
  return GLYPH[CLINICAL_STATUS[status].icon] ?? '•';
}

/**
 * Marker inside a workflow stage circle.
 *
 * The step number is the neutral case. A glyph appears only where the stage
 * needs attention, so a glyph anywhere means something requires action.
 */
export function stageMarker(state: WorkflowStageState, step: number): string {
  switch (state) {
    case 'COMPLETE':
      return glyphFor('COMPLETED');
    case 'BLOCKED':
      return glyphFor('BLOCKING');
    case 'STALE':
      return glyphFor('STALE');
    case 'ACTION_REQUIRED':
      return glyphFor('ACTION_REQUIRED');
    default:
      return String(step);
  }
}
