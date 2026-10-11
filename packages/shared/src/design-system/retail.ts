/**
 * Presentation guidance for the native retail basket.
 *
 * This module never authorises a transaction. It picks the one action the UI
 * should emphasise from the transaction state supplied by the POS API, keeping
 * Windows and Android language aligned without inventing a settlement result.
 */
export type RetailPrimaryActionKind =
  | 'START_SALE'
  | 'RESUME_SALE'
  | 'PREPARE_PAYMENT'
  | 'SETTLE_CASH'
  | 'NONE';

export interface RetailPrimaryAction {
  readonly kind: RetailPrimaryActionKind;
  readonly label: string;
  readonly detail: string;
  readonly enabled: boolean;
}

export function deriveRetailPrimaryAction({
  state,
  lineCount,
  hasStore,
}: {
  readonly state: string | null;
  readonly lineCount: number;
  readonly hasStore: boolean;
}): RetailPrimaryAction {
  if (state === null) {
    return hasStore
      ? {
          kind: 'START_SALE',
          label: 'Start new sale',
          detail: 'Open a register-bound basket for the selected store.',
          enabled: true,
        }
      : {
          kind: 'NONE',
          label: 'Select a store to start',
          detail: 'An active store is required before a retail basket can be opened.',
          enabled: false,
        };
  }

  if (state === 'HELD') {
    return {
      kind: 'RESUME_SALE',
      label: 'Resume sale',
      detail: 'Return this held basket to its authoritative editable state.',
      enabled: true,
    };
  }

  if (state === 'DRAFT' && lineCount === 0) {
    return {
      kind: 'NONE',
      label: 'Add an item to continue',
      detail: 'Scan a barcode or search the sellable catalogue.',
      enabled: false,
    };
  }

  if (state === 'DRAFT') {
    return {
      kind: 'PREPARE_PAYMENT',
      label: 'Prepare payment',
      detail: 'Validate the authoritative basket before settlement.',
      enabled: true,
    };
  }

  if (state === 'READY_FOR_PAYMENT') {
    return {
      kind: 'SETTLE_CASH',
      label: 'Settle cash payment',
      detail: 'Cash only. Card and M-PESA settlement remain unavailable.',
      enabled: true,
    };
  }

  if (state === 'CANCELLED' || state === 'COMPLETED' || state === 'PAID') {
    return {
      kind: 'START_SALE',
      label: 'Start new sale',
      detail: 'Open a fresh register-bound basket.',
      enabled: hasStore,
    };
  }

  return {
    kind: 'NONE',
    label: 'Action unavailable',
    detail: `This sale is currently ${state.replace(/_/g, ' ').toLowerCase()}.`,
    enabled: false,
  };
}
