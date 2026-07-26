/**
 * Semantic status vocabulary for the TibaTrace clinical POS.
 *
 * Windows and Android share these *semantics*, not their rendering. Each
 * platform draws them natively; what must never diverge is what a status means,
 * whether it blocks progression, and how it is described to an operator.
 *
 * Two rules run through this file:
 *
 * 1. Colour is never the only signal. Every status carries a label and an icon
 *    name as well, because a dispensing decision must survive colour-blindness,
 *    a sun-washed till screen and a monochrome remote session.
 * 2. Nothing here decides clinical safety. These are presentation semantics for
 *    state the server already determined. `SAFE` describes an authoritative
 *    server answer; it never produces one.
 */

export type ClinicalStatus =
  | 'SAFE'
  | 'INFORMATION'
  | 'ACTION_REQUIRED'
  | 'PHARMACIST_REVIEW'
  | 'BLOCKING'
  | 'STALE'
  | 'OFFLINE'
  | 'PROCESSING'
  | 'COMPLETED'
  | 'DISABLED';

export interface ClinicalStatusMeta {
  /** Short label. Always rendered -- colour alone is never sufficient. */
  readonly label: string;
  /** Platform-neutral icon name; each client maps it to its own icon set. */
  readonly icon: string;
  /** Whether workflow progression is prohibited in this state. */
  readonly blocksProgression: boolean;
  /**
   * Whether the operator must do something to move on.
   *
   * Distinct from `blocksProgression`, and the difference decides how the state
   * is announced. PROCESSING and DISABLED both block, but neither asks anything
   * of the operator: one resolves itself, the other is a passive absence.
   * Interrupting a screen reader for those would train operators to ignore the
   * interruptions that matter.
   *
   * Every state where this is true must announce assertively -- a demand the
   * operator only discovers by exploring is a demand discovered too late.
   */
  readonly demandsAction: boolean;
  /** Severity ordering, for sorting findings and picking the summary state. */
  readonly weight: number;
  /** Accessible announcement politeness for live regions. */
  readonly announce: 'off' | 'polite' | 'assertive';
  readonly description: string;
}

export const CLINICAL_STATUS: Readonly<Record<ClinicalStatus, ClinicalStatusMeta>> = {
  BLOCKING: {
    label: 'Blocking',
    icon: 'octagon-x',
    blocksProgression: true,
    demandsAction: true,
    weight: 100,
    announce: 'assertive',
    description: 'Progression is prohibited until this is resolved.',
  },
  PHARMACIST_REVIEW: {
    label: 'Pharmacist review',
    icon: 'user-check',
    blocksProgression: true,
    demandsAction: true,
    weight: 90,
    announce: 'assertive',
    description: 'A pharmacist or elevated clinical authority must decide.',
  },
  STALE: {
    label: 'No longer valid',
    icon: 'history',
    blocksProgression: true,
    demandsAction: true,
    weight: 80,
    announce: 'assertive',
    description: 'The prescription or basket changed after approval. Re-screening is required.',
  },
  OFFLINE: {
    label: 'Offline',
    icon: 'cloud-off',
    blocksProgression: false,
    demandsAction: false,
    weight: 70,
    announce: 'polite',
    description: 'Operating under constrained offline policy.',
  },
  ACTION_REQUIRED: {
    label: 'Action required',
    icon: 'alert-triangle',
    blocksProgression: true,
    demandsAction: true,
    weight: 60,
    announce: 'assertive',
    description: 'Operator action is required before progression.',
  },
  PROCESSING: {
    label: 'Processing',
    icon: 'loader',
    blocksProgression: true,
    demandsAction: false,
    weight: 50,
    announce: 'polite',
    description: 'Awaiting an authoritative response.',
  },
  INFORMATION: {
    label: 'Information',
    icon: 'info',
    blocksProgression: false,
    demandsAction: false,
    weight: 40,
    announce: 'off',
    description: 'Informational only; does not block progression.',
  },
  COMPLETED: {
    label: 'Complete',
    icon: 'check-circle',
    blocksProgression: false,
    demandsAction: false,
    weight: 30,
    announce: 'polite',
    description: 'This stage is complete.',
  },
  SAFE: {
    label: 'Safe to proceed',
    icon: 'shield-check',
    blocksProgression: false,
    demandsAction: false,
    weight: 20,
    announce: 'polite',
    description: 'Clinical screening is current with no unresolved blocking findings.',
  },
  DISABLED: {
    label: 'Unavailable',
    icon: 'lock',
    blocksProgression: true,
    demandsAction: false,
    weight: 10,
    announce: 'off',
    description: 'Not available in the current state.',
  },
};

/**
 * Pick the single status that should headline a summary.
 *
 * Highest severity wins. An operator must see the blocker first rather than
 * scrolling past informational findings to discover why they are stuck.
 */
export function dominantStatus(statuses: readonly ClinicalStatus[]): ClinicalStatus {
  if (statuses.length === 0) return 'INFORMATION';
  return statuses.reduce((worst, candidate) =>
    CLINICAL_STATUS[candidate].weight > CLINICAL_STATUS[worst].weight ? candidate : worst,
  );
}

export function blocksProgression(status: ClinicalStatus): boolean {
  return CLINICAL_STATUS[status].blocksProgression;
}

/**
 * Allergy status is deliberately three-valued.
 *
 * "Unknown" must never render like "none known": absence of recorded allergies
 * is not evidence of absence, and a banner that shows them alike invites a
 * dispenser to treat an unassessed patient as cleared.
 */
export type AllergyStatus = 'NONE_KNOWN' | 'KNOWN_ALLERGY' | 'UNKNOWN';

export const ALLERGY_STATUS: Readonly<
  Record<AllergyStatus, { readonly label: string; readonly status: ClinicalStatus }>
> = {
  KNOWN_ALLERGY: { label: 'Known allergy', status: 'BLOCKING' },
  UNKNOWN: { label: 'Allergy status unknown', status: 'ACTION_REQUIRED' },
  NONE_KNOWN: { label: 'No known allergies', status: 'SAFE' },
};

/** Patient safety badges surfaced in the persistent banner. */
export type SafetyBadge =
  | 'KNOWN_ALLERGY'
  | 'NO_KNOWN_ALLERGIES'
  | 'ALLERGY_STATUS_UNKNOWN'
  | 'HIGH_RISK_MEDICINE'
  | 'CONTROLLED_MEDICINE'
  | 'CHILD'
  | 'OLDER_PATIENT'
  | 'PREGNANCY_ALERT'
  | 'RENAL_RISK'
  | 'REPEAT_DISPENSING';

export const SAFETY_BADGE: Readonly<
  Record<SafetyBadge, { readonly label: string; readonly status: ClinicalStatus }>
> = {
  KNOWN_ALLERGY: { label: 'Known allergy', status: 'BLOCKING' },
  ALLERGY_STATUS_UNKNOWN: { label: 'Allergy status unknown', status: 'ACTION_REQUIRED' },
  NO_KNOWN_ALLERGIES: { label: 'No known allergies', status: 'SAFE' },
  HIGH_RISK_MEDICINE: { label: 'High-risk medicine', status: 'PHARMACIST_REVIEW' },
  CONTROLLED_MEDICINE: { label: 'Controlled medicine', status: 'PHARMACIST_REVIEW' },
  PREGNANCY_ALERT: { label: 'Pregnancy alert', status: 'PHARMACIST_REVIEW' },
  RENAL_RISK: { label: 'Renal risk', status: 'ACTION_REQUIRED' },
  CHILD: { label: 'Child', status: 'INFORMATION' },
  OLDER_PATIENT: { label: 'Older patient', status: 'INFORMATION' },
  REPEAT_DISPENSING: { label: 'Repeat dispensing', status: 'INFORMATION' },
};

/** Connectivity, which is not a simple binary in a dispensing context. */
export type ConnectivityState =
  | 'ONLINE'
  | 'DEGRADED'
  | 'OFFLINE_VERIFIED_PACKAGE'
  | 'OFFLINE_DISPENSING_BLOCKED'
  | 'SYNC_PENDING';

export const CONNECTIVITY: Readonly<
  Record<ConnectivityState, { readonly label: string; readonly status: ClinicalStatus }>
> = {
  ONLINE: { label: 'Online', status: 'SAFE' },
  DEGRADED: { label: 'Degraded', status: 'ACTION_REQUIRED' },
  OFFLINE_VERIFIED_PACKAGE: { label: 'Offline — verified package', status: 'OFFLINE' },
  OFFLINE_DISPENSING_BLOCKED: { label: 'Offline — dispensing blocked', status: 'BLOCKING' },
  SYNC_PENDING: { label: 'Sync pending', status: 'INFORMATION' },
};
