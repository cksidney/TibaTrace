import { CLINICAL_STATUS } from '@dawatrace/shared/design-system/index.js';
import type { ClinicalStatus } from '@dawatrace/shared/design-system/index.js';

/**
 * Map a clinical status to React Native's `accessibilityLiveRegion`.
 *
 * One function so the mapping cannot drift between screens. PaymentScreen
 * previously hardcoded `status === 'BLOCKING' ? 'assertive' : 'polite'`, which
 * left PHARMACIST_REVIEW, STALE and ACTION_REQUIRED -- all states that stop the
 * operator and ask something of them -- queued behind whatever TalkBack was
 * already reading.
 *
 * `off` maps to `none` rather than `polite`. Announcing purely informational
 * state is how operators learn to tune the announcements out.
 */
export function liveRegionFor(status: ClinicalStatus): 'none' | 'polite' | 'assertive' {
  const announce = CLINICAL_STATUS[status].announce;
  if (announce === 'assertive') return 'assertive';
  if (announce === 'polite') return 'polite';
  return 'none';
}
