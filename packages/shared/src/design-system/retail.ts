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
      kind: 'NONE',
      label: 'Settlement required',
      detail: 'Retail settlement is not available in this POS pilot.',
      enabled: false,
    };
  }

  if (state === 'CANCELLED') {
    return {
      kind: 'NONE',
      label: 'Sale cancelled',
      detail: 'Start a new sale to continue serving the customer.',
      enabled: false,
    };
  }

  return {
    kind: 'NONE',
    label: 'Action unavailable',
    detail: `This sale is currently ${state.replace(/_/g, ' ').toLowerCase()}.`,
    enabled: false,
  };
}
