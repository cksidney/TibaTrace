import { describe, expect, it } from 'vitest';

import { SHORTCUTS, performsPrivilegedAction, resolveShortcut } from './keyboard.js';
import { compareLine, hasMismatch } from '../components/tibatrace/FinalCheck.js';
import type { DispensingLineDTO } from '@dawatrace/shared/dispensing/index.js';

function line(overrides: Partial<DispensingLineDTO> = {}): DispensingLineDTO {
  return {
    id: 'l-1',
    prescription_item: 'pi-1',
    prescribed_sku: 'SKU-A',
    supplied_sku: 'SKU-A',
    inventory_batch: 'b-1',
    quantity_authorized: '30',
    quantity_prepared: '30',
    quantity_supplied: '0',
    unit: 'TABLET',
    batch_number_snapshot: 'B123',
    expiry_date_snapshot: '2028-12-31',
    dosage_label_instructions: 'Take one three times a day',
    status: 'PREPARED',
    ...overrides,
  } as DispensingLineDTO;
}

describe('keyboard shortcuts', () => {
  it('binds no shortcut to a clinical, financial or custody action', () => {
    // A stray keypress must never move money or release stock.
    for (const binding of SHORTCUTS) {
      expect(performsPrivilegedAction(binding), `${binding.key} must not act`).toBe(false);
    }
  });

  it('resolves function keys to their stage', () => {
    expect(resolveShortcut({ key: 'F8' })).toBe('PAYMENT');
    expect(resolveShortcut({ key: 'F5' })).toBe('CLINICAL_FINDINGS');
    expect(resolveShortcut({ key: 'F12' })).toBe('SCAN_FOCUS');
  });

  it('requires the modifier where one is declared', () => {
    expect(resolveShortcut({ key: 'r' })).toBeNull();
    expect(resolveShortcut({ key: 'r', ctrlKey: true })).toBe('REFRESH');
  });

  it('does not fire character shortcuts while typing', () => {
    // Typing a batch number must not trigger a refresh.
    const input = document.createElement('input');
    expect(resolveShortcut({ key: 'r', ctrlKey: true, target: input })).toBeNull();
  });

  it('still allows escape while typing', () => {
    // An operator must always be able to back out of a drawer mid-entry.
    const input = document.createElement('input');
    expect(resolveShortcut({ key: 'Escape', target: input })).toBe('CLOSE');
  });

  it('still allows function keys while typing', () => {
    const input = document.createElement('input');
    expect(resolveShortcut({ key: 'F2', target: input })).toBe('SEARCH_MEDICINE');
  });

  it('has no duplicate bindings', () => {
    const seen = SHORTCUTS.map((s) => `${s.ctrl ? 'ctrl+' : ''}${s.key}`);
    expect(new Set(seen).size).toBe(seen.length);
  });
});

describe('final check comparison', () => {
  it('passes a line where prepared matches prescribed', () => {
    expect(hasMismatch([line()])).toBe(false);
  });

  it('flags a different product', () => {
    expect(hasMismatch([line({ supplied_sku: 'SKU-B' })])).toBe(true);
  });

  it('flags a different quantity', () => {
    expect(hasMismatch([line({ quantity_prepared: '20' })])).toBe(true);
  });

  it('does not flag equivalent quantities written differently', () => {
    // "30" and "30.0000" are the same medicine. Flagging it would train
    // checkers to dismiss the warning.
    expect(hasMismatch([line({ quantity_prepared: '30.0000' })])).toBe(false);
  });

  it('does not compare batch against a prescription that never specified one', () => {
    const rows = compareLine(line());
    const batch = rows.find((r) => r.field === 'Batch');
    expect(batch?.matches).toBe(true);
    expect(batch?.prepared).toBe('B123');
  });

  it('reports a mismatch across any line in the basket', () => {
    expect(hasMismatch([line(), line({ id: 'l-2', quantity_prepared: '10' })])).toBe(true);
  });
});
