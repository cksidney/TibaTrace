import type { PaymentMode } from './types.js';

/**
 * Which tenders the POS may offer, and why the others cannot be used.
 *
 * Declared once here rather than per-client. Windows and Android previously
 * held their own copies, which meant one could quietly start offering a payment
 * route the other refused -- and a tender the server cannot settle lets an
 * operator begin a payment the system cannot finish.
 *
 * A tender becomes available only when its settlement path exists on the
 * server.
 */
export interface TenderOption {
  readonly type: PaymentMode;
  readonly label: string;
  readonly available: boolean;
  /** Shown to the operator verbatim when the tender is unavailable. */
  readonly blocker?: string;
}

export const TENDER_OPTIONS: readonly TenderOption[] = [
  { type: 'CASH', label: 'Cash', available: true },
  // Named "manual approval" deliberately: nothing here integrates with a card
  // terminal, and the UI must not imply that it does.
  { type: 'CARD', label: 'Card (manual approval)', available: true },
  {
    type: 'MPESA',
    label: 'M-PESA',
    available: false,
    blocker: 'M-PESA settlement is not yet available on this deployment.',
  },
  // Enabled once the server gained intent/tender allocation, settlement
  // orchestration and the API to drive them. It was disabled while those were
  // absent rather than shown as a control that could not complete.
  { type: 'SPLIT', label: 'Split tender', available: true },
];

export function tenderIsAvailable(mode: PaymentMode): boolean {
  return TENDER_OPTIONS.some((option) => option.type === mode && option.available);
}
