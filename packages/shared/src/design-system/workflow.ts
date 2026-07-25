/**
 * The dispensing workflow ribbon.
 *
 * Stage state is *derived from authoritative server state*, never from whether
 * an operator visited a screen. Visiting the payment tab does not make payment
 * complete, and a ribbon that implied otherwise would be actively misleading in
 * a dispensing context.
 */
import type { ClinicalStatus } from './clinicalStatus.js';
import type { DispensingEpisodeDTO, PaymentState } from '../dispensing/types.js';
import { paymentPermitsSupply } from '../dispensing/types.js';

export type WorkflowStageId =
  | 'PATIENT'
  | 'PRESCRIPTION'
  | 'CLINICAL_SCREENING'
  | 'PHARMACIST_VERIFICATION'
  | 'PREPARATION'
  | 'FINAL_CHECK'
  | 'PAYMENT'
  | 'SUPPLY'
  | 'COLLECTION';

export type WorkflowStageState =
  | 'NOT_STARTED'
  | 'IN_PROGRESS'
  | 'ACTION_REQUIRED'
  | 'BLOCKED'
  | 'COMPLETE'
  | 'STALE'
  | 'NOT_APPLICABLE';

export const WORKFLOW_STAGES: readonly { id: WorkflowStageId; label: string; step: number }[] = [
  { id: 'PATIENT', label: 'Patient', step: 1 },
  { id: 'PRESCRIPTION', label: 'Prescription', step: 2 },
  { id: 'CLINICAL_SCREENING', label: 'Clinical screening', step: 3 },
  { id: 'PHARMACIST_VERIFICATION', label: 'Pharmacist verification', step: 4 },
  { id: 'PREPARATION', label: 'Preparation', step: 5 },
  { id: 'FINAL_CHECK', label: 'Final check', step: 6 },
  { id: 'PAYMENT', label: 'Payment', step: 7 },
  { id: 'SUPPLY', label: 'Supply', step: 8 },
  { id: 'COLLECTION', label: 'Collection', step: 9 },
];

export const STAGE_STATUS: Readonly<Record<WorkflowStageState, ClinicalStatus>> = {
  NOT_STARTED: 'DISABLED',
  IN_PROGRESS: 'PROCESSING',
  ACTION_REQUIRED: 'ACTION_REQUIRED',
  BLOCKED: 'BLOCKING',
  COMPLETE: 'COMPLETED',
  STALE: 'STALE',
  NOT_APPLICABLE: 'DISABLED',
};

export interface StageView {
  readonly id: WorkflowStageId;
  readonly label: string;
  readonly step: number;
  readonly state: WorkflowStageState;
  /** Why the operator cannot act here. Empty when the stage is not blocked. */
  readonly blockedReason: string;
  /** Whether selecting the stage may navigate to it. */
  readonly navigable: boolean;
}

/**
 * Derive the ribbon from an episode.
 *
 * `clinicalStale` and `screeningSafe` come from the clinical screening API
 * rather than the episode, so they are passed in explicitly instead of being
 * inferred here -- inference is exactly how a client ends up inventing safety.
 */
export function deriveStages(
  episode: DispensingEpisodeDTO | null,
  clinical: {
    readonly screened: boolean;
    readonly safeToProceed: boolean;
    readonly stale: boolean;
    readonly pharmacistReviewRequired: boolean;
  } = { screened: false, safeToProceed: false, stale: false, pharmacistReviewRequired: false },
): readonly StageView[] {
  const status = episode?.status ?? null;
  const payment: PaymentState | null = episode?.payment_state ?? null;

  const reached = (stages: readonly string[]) => (status ? stages.includes(status) : false);

  const clinicalState: WorkflowStageState = !episode
    ? 'NOT_STARTED'
    : clinical.stale
      ? 'STALE'
      : !clinical.screened
        ? 'ACTION_REQUIRED'
        : clinical.pharmacistReviewRequired
          ? 'BLOCKED'
          : clinical.safeToProceed
            ? 'COMPLETE'
            : 'ACTION_REQUIRED';

  const paymentState: WorkflowStageState = !payment
    ? 'NOT_STARTED'
    : payment === 'NOT_REQUIRED' || payment === 'WAIVED'
      ? 'NOT_APPLICABLE'
      : payment === 'PAID'
        ? 'COMPLETE'
        : payment === 'PARTIALLY_PAID'
          ? 'ACTION_REQUIRED'
          : payment === 'FAILED' || payment === 'CANCELLED'
            ? 'BLOCKED'
            : payment === 'REVERSAL_PENDING' || payment === 'REVERSED' || payment === 'REFUNDED'
              ? 'BLOCKED'
              : status === 'READY_FOR_PAYMENT'
                ? 'ACTION_REQUIRED'
                : 'NOT_STARTED';

  const supplyPermitted = payment !== null && paymentPermitsSupply(payment);

  const stageStates: Record<WorkflowStageId, { state: WorkflowStageState; reason: string }> = {
    PATIENT: { state: episode ? 'COMPLETE' : 'NOT_STARTED', reason: '' },
    PRESCRIPTION: { state: episode ? 'COMPLETE' : 'NOT_STARTED', reason: '' },
    CLINICAL_SCREENING: {
      state: clinicalState,
      reason:
        clinicalState === 'STALE'
          ? 'The prescription changed after approval. Re-screening is required.'
          : clinicalState === 'BLOCKED'
            ? 'A pharmacist decision is required before progression.'
            : clinicalState === 'ACTION_REQUIRED'
              ? 'Clinical screening must be completed.'
              : '',
    },
    PHARMACIST_VERIFICATION: {
      state: !episode
        ? 'NOT_STARTED'
        : reached(['CHECKING', 'READY_FOR_PAYMENT', 'PAID', 'READY_FOR_SUPPLY', 'READY_FOR_COLLECTION', 'PARTIALLY_SUPPLIED', 'SUPPLIED', 'CLOSED'])
          ? 'COMPLETE'
          : 'ACTION_REQUIRED',
      reason: '',
    },
    PREPARATION: {
      state: !episode
        ? 'NOT_STARTED'
        : status === 'PREPARING'
          ? 'IN_PROGRESS'
          : reached(['CHECKING', 'READY_FOR_PAYMENT', 'PAID', 'READY_FOR_SUPPLY', 'READY_FOR_COLLECTION', 'PARTIALLY_SUPPLIED', 'SUPPLIED', 'CLOSED'])
            ? 'COMPLETE'
            : 'NOT_STARTED',
      reason: '',
    },
    FINAL_CHECK: {
      state: !episode
        ? 'NOT_STARTED'
        : status === 'CHECKING'
          ? 'IN_PROGRESS'
          : reached(['READY_FOR_PAYMENT', 'PAID', 'READY_FOR_SUPPLY', 'READY_FOR_COLLECTION', 'PARTIALLY_SUPPLIED', 'SUPPLIED', 'CLOSED'])
            ? 'COMPLETE'
            : 'NOT_STARTED',
      reason: '',
    },
    PAYMENT: {
      state: paymentState,
      reason:
        paymentState === 'ACTION_REQUIRED' && payment === 'PARTIALLY_PAID'
          ? 'Partially paid. The balance must be settled before supply.'
          : paymentState === 'BLOCKED'
            ? `Payment state is ${payment}.`
            : '',
    },
    SUPPLY: {
      state: !episode
        ? 'NOT_STARTED'
        : status === 'SUPPLIED' || status === 'CLOSED'
          ? 'COMPLETE'
          : status === 'PARTIALLY_SUPPLIED'
            ? 'IN_PROGRESS'
            : !supplyPermitted
              ? 'BLOCKED'
              : reached(['READY_FOR_SUPPLY', 'READY_FOR_COLLECTION'])
                ? 'ACTION_REQUIRED'
                : 'NOT_STARTED',
      reason: supplyPermitted ? '' : 'Supply is not permitted until payment is settled.',
    },
    COLLECTION: {
      state: !episode
        ? 'NOT_STARTED'
        : episode.collected_at
          ? 'COMPLETE'
          : status === 'SUPPLIED'
            ? 'ACTION_REQUIRED'
            : 'NOT_STARTED',
      reason: '',
    },
  };

  return WORKFLOW_STAGES.map((stage) => {
    const derived = stageStates[stage.id];
    return {
      id: stage.id,
      label: stage.label,
      step: stage.step,
      state: derived.state,
      blockedReason: derived.reason,
      // A stage that has not started is not navigable: a later stage must never
      // become a route around an incomplete earlier one.
      navigable: derived.state !== 'NOT_STARTED' && derived.state !== 'NOT_APPLICABLE',
    };
  });
}

/** The single next lawful action, for the contextual action bar. */
export function nextAction(stages: readonly StageView[]): StageView | null {
  return (
    stages.find((s) => s.state === 'BLOCKED' || s.state === 'STALE') ??
    stages.find((s) => s.state === 'ACTION_REQUIRED') ??
    stages.find((s) => s.state === 'IN_PROGRESS') ??
    null
  );
}
