/**
 * Split-tender allocation, shared by both clients.
 *
 * Mirrors SplitTenderService on the server. This computes what the till should
 * *display* while an operator builds an allocation; the server recomputes
 * everything from settlement rows and has the final say.
 *
 * The distinction that matters throughout: allocated is not settled, and
 * pending is neither. A tender someone has keyed in is a plan. A tender a
 * provider has not yet confirmed is a hope. Only settled value counts as money.
 */
import type { PaymentTenderType } from './types.js';

export type TenderLineStatus =
  | 'ALLOCATED'
  | 'PENDING'
  | 'PARTIALLY_SETTLED'
  | 'SETTLED'
  | 'FAILED'
  | 'CANCELLED';

export interface TenderLine {
  readonly id: string;
  readonly tenderType: PaymentTenderType;
  readonly allocated: number;
  readonly settled: number;
  readonly status: TenderLineStatus;
}

export interface SplitTenderSummary {
  readonly amountDue: number;
  readonly allocated: number;
  readonly settled: number;
  readonly pending: number;
  readonly failed: number;
  readonly unallocated: number;
  readonly remaining: number;
  readonly fullyAllocated: boolean;
  readonly fullySettled: boolean;
  /** Cash handed back, only ever from an over-tendered cash line. */
  readonly changeDue: number;
}

/** Statuses that still count toward the intent's allocation. */
const LIVE: readonly TenderLineStatus[] = [
  'ALLOCATED',
  'PENDING',
  'PARTIALLY_SETTLED',
  'SETTLED',
];

export function summarise(
  amountDue: number,
  lines: readonly TenderLine[],
  cashReceived = 0,
): SplitTenderSummary {
  const live = lines.filter((line) => LIVE.includes(line.status));
  const allocated = sum(live.map((line) => line.allocated));
  const settled = sum(live.map((line) => line.settled));

  // A provider attempt in flight is deliberately excluded from settled. If it
  // were counted, a till would show a sale as complete while the customer had
  // not yet approved anything on their handset.
  const pending = sum(
    live
      .filter((line) => line.status === 'PENDING' || line.status === 'PARTIALLY_SETTLED')
      .map((line) => line.allocated - line.settled),
  );
  const failed = sum(lines.filter((l) => l.status === 'FAILED').map((l) => l.allocated));

  const cashAllocated = sum(
    live.filter((line) => line.tenderType === 'CASH').map((line) => line.allocated),
  );

  return {
    amountDue,
    allocated,
    settled,
    pending,
    failed,
    unallocated: round(Math.max(0, amountDue - allocated)),
    remaining: round(Math.max(0, amountDue - settled)),
    fullyAllocated: allocated >= amountDue,
    fullySettled: amountDue > 0 && settled >= amountDue,
    // Change comes only from cash actually handed over, never from an
    // over-allocation on a card or provider tender -- those cannot give change.
    changeDue: round(Math.max(0, cashReceived - cashAllocated)),
  };
}

export type AllocationError =
  | 'NOT_POSITIVE'
  | 'EXCEEDS_AMOUNT_DUE'
  | 'TENDER_UNAVAILABLE'
  | 'NOTHING_OUTSTANDING';

/**
 * Whether another tender line may be added.
 *
 * Rejects rather than clamps: silently reducing an operator's figure to fit
 * would leave them believing they collected more than the record shows.
 */
export function validateAllocation(
  amountDue: number,
  lines: readonly TenderLine[],
  addition: { amount: number; tenderType: PaymentTenderType; available: boolean },
): AllocationError | null {
  if (!addition.available) return 'TENDER_UNAVAILABLE';
  if (!(addition.amount > 0)) return 'NOT_POSITIVE';

  const current = summarise(amountDue, lines);
  if (current.unallocated <= 0) return 'NOTHING_OUTSTANDING';
  if (round(current.allocated + addition.amount) > amountDue) return 'EXCEEDS_AMOUNT_DUE';
  return null;
}

export function describeAllocationError(error: AllocationError, amountRemaining: number): string {
  switch (error) {
    case 'NOT_POSITIVE':
      return 'Enter an amount greater than zero.';
    case 'EXCEEDS_AMOUNT_DUE':
      return `That would allocate more than is owed. ${amountRemaining.toFixed(2)} remains unallocated.`;
    case 'TENDER_UNAVAILABLE':
      return 'That tender is not available on this deployment.';
    case 'NOTHING_OUTSTANDING':
      return 'The full amount is already allocated.';
  }
}

function sum(values: readonly number[]): number {
  return round(values.reduce((total, value) => total + value, 0));
}

/** Money is rounded to cents at every step so display never drifts. */
function round(value: number): number {
  return Math.round(value * 100) / 100;
}
