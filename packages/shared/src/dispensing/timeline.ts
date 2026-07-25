/**
 * Episode timeline.
 *
 * A readable operational history, not raw audit JSON. Someone reconstructing
 * what happened to a prescription — a pharmacist the next morning, an auditor
 * months later — needs to read it in order and understand it without knowing
 * the event schema.
 *
 * Entries are never synthesised. Every one corresponds to something the server
 * recorded; a gap in the timeline means a gap in the audit trail, and papering
 * over it would hide exactly what an investigation needs to find.
 */
import type { ClinicalStatus } from '../design-system/clinicalStatus.js';

export type TimelineEventType =
  | 'PRESCRIPTION_LOADED'
  | 'SCREENING_COMPLETED'
  | 'SCREENING_INVALIDATED'
  | 'FINDING_ACKNOWLEDGED'
  | 'PHARMACIST_REVIEW_REQUESTED'
  | 'PHARMACIST_DECISION_RECORDED'
  | 'OVERRIDE_REQUESTED'
  | 'OVERRIDE_APPROVED'
  | 'BASKET_CHANGED'
  | 'MEDICINE_PREPARED'
  | 'FINAL_CHECK_COMPLETED'
  | 'PAYMENT_INITIATED'
  | 'PAYMENT_SETTLED'
  | 'PAYMENT_REVERSED'
  | 'MEDICINE_SUPPLIED'
  | 'MEDICINE_COLLECTED'
  | 'LABEL_PRINTED'
  | 'LABEL_REPRINTED'
  | 'OFFLINE_SUPPLY_RECONCILED'
  | 'OFFLINE_SYNC_CONFLICT'
  | 'CLINICAL_CONTEXT_STALE'
  | 'CAPABILITY_DENIED';

export interface TimelineEntry {
  readonly id: string;
  readonly type: TimelineEventType;
  readonly occurredAt: string;
  readonly actor: string;
  readonly summary: string;
  /** Present only where the server recorded one. Never invented. */
  readonly reason?: string;
}

interface EventPresentation {
  readonly label: string;
  readonly status: ClinicalStatus;
  /** Whether this entry deserves emphasis when scanning the history. */
  readonly notable: boolean;
}

/**
 * How each event reads in the timeline.
 *
 * Refusals, reversals and staleness are marked notable: when someone opens a
 * timeline they are usually looking for the moment something went wrong, and
 * those moments must not sit at the same visual weight as routine progress.
 */
export const TIMELINE_EVENTS: Readonly<Record<TimelineEventType, EventPresentation>> = {
  PRESCRIPTION_LOADED: { label: 'Prescription loaded', status: 'INFORMATION', notable: false },
  SCREENING_COMPLETED: { label: 'Clinical screening completed', status: 'SAFE', notable: false },
  SCREENING_INVALIDATED: {
    label: 'Screening invalidated',
    status: 'STALE',
    notable: true,
  },
  FINDING_ACKNOWLEDGED: { label: 'Finding acknowledged', status: 'INFORMATION', notable: false },
  PHARMACIST_REVIEW_REQUESTED: {
    label: 'Pharmacist review requested',
    status: 'PHARMACIST_REVIEW',
    notable: true,
  },
  PHARMACIST_DECISION_RECORDED: {
    label: 'Pharmacist decision recorded',
    status: 'PHARMACIST_REVIEW',
    notable: true,
  },
  OVERRIDE_REQUESTED: { label: 'Clinical override requested', status: 'PHARMACIST_REVIEW', notable: true },
  OVERRIDE_APPROVED: { label: 'Clinical override approved', status: 'PHARMACIST_REVIEW', notable: true },
  BASKET_CHANGED: { label: 'Basket changed', status: 'STALE', notable: true },
  MEDICINE_PREPARED: { label: 'Medicine prepared', status: 'INFORMATION', notable: false },
  FINAL_CHECK_COMPLETED: { label: 'Final check completed', status: 'SAFE', notable: false },
  PAYMENT_INITIATED: { label: 'Payment initiated', status: 'PROCESSING', notable: false },
  PAYMENT_SETTLED: { label: 'Payment settled', status: 'COMPLETED', notable: false },
  PAYMENT_REVERSED: { label: 'Payment reversed', status: 'BLOCKING', notable: true },
  MEDICINE_SUPPLIED: { label: 'Medicine supplied', status: 'COMPLETED', notable: false },
  MEDICINE_COLLECTED: { label: 'Medicine collected', status: 'COMPLETED', notable: false },
  LABEL_PRINTED: { label: 'Label printed', status: 'INFORMATION', notable: false },
  LABEL_REPRINTED: { label: 'Label reprinted', status: 'ACTION_REQUIRED', notable: true },
  OFFLINE_SUPPLY_RECONCILED: {
    label: 'Offline supply reconciled',
    status: 'INFORMATION',
    notable: false,
  },
  OFFLINE_SYNC_CONFLICT: { label: 'Offline sync conflict', status: 'BLOCKING', notable: true },
  CLINICAL_CONTEXT_STALE: { label: 'Clinical context stale', status: 'STALE', notable: true },
  CAPABILITY_DENIED: { label: 'Action refused', status: 'BLOCKING', notable: true },
};

/** Map a raw server event type onto a timeline type, or null if unrecognised. */
export function toTimelineType(raw: string): TimelineEventType | null {
  const direct = raw as TimelineEventType;
  if (direct in TIMELINE_EVENTS) return direct;

  // The server names some events differently from the timeline vocabulary.
  const aliases: Record<string, TimelineEventType> = {
    DISPENSING_PAYMENT_PROCESSED: 'PAYMENT_SETTLED',
    PaymentSettlementRecorded: 'PAYMENT_SETTLED',
    PaymentReversalCompleted: 'PAYMENT_REVERSED',
    PaymentAttemptStarted: 'PAYMENT_INITIATED',
    MEDICINE_SUPPLIED: 'MEDICINE_SUPPLIED',
    MEDICINE_COLLECTED: 'MEDICINE_COLLECTED',
    SCREENING_COMPLETED: 'SCREENING_COMPLETED',
    SCREENING_INVALIDATED: 'SCREENING_INVALIDATED',
    FINDING_ACKNOWLEDGED: 'FINDING_ACKNOWLEDGED',
    PHARMACIST_REVIEW_REQUESTED: 'PHARMACIST_REVIEW_REQUESTED',
    FINDING_RESOLVED: 'PHARMACIST_DECISION_RECORDED',
    OVERRIDE_RECORDED: 'OVERRIDE_APPROVED',
    LabelPrinted: 'LABEL_PRINTED',
    LabelReprinted: 'LABEL_REPRINTED',
  };
  return aliases[raw] ?? null;
}

/**
 * Order a timeline oldest-first.
 *
 * Stable on equal timestamps so two events recorded in the same millisecond do
 * not reorder between renders — an audit view that shuffles is one nobody
 * trusts.
 */
export function orderTimeline(entries: readonly TimelineEntry[]): readonly TimelineEntry[] {
  return [...entries]
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) => {
      const byTime = Date.parse(a.entry.occurredAt) - Date.parse(b.entry.occurredAt);
      if (byTime !== 0 && Number.isFinite(byTime)) return byTime;
      return a.index - b.index;
    })
    .map(({ entry }) => entry);
}

export function notableEntries(entries: readonly TimelineEntry[]): readonly TimelineEntry[] {
  return entries.filter((entry) => TIMELINE_EVENTS[entry.type]?.notable);
}
