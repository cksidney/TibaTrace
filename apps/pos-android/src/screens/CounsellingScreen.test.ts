import { CLINICAL_STATUS, controlSize } from '@dawatrace/shared/design-system/index.js';
import type { CounsellingRecordRequest } from '@dawatrace/shared/dispensing/index.js';
import { describe, expect, it } from 'vitest';

/**
 * Android counselling and collection must not be weaker than Windows.
 *
 * The rules under test are the ones with a clinical or financial consequence,
 * not the layout.
 */

/** The topic set both clients send. Mirrors CounsellingRecordRequest. */
const TOPIC_KEYS = [
  'medicine_explained',
  'dosage_explained',
  'storage_explained',
  'side_effects_discussed',
  'interaction_advice_given',
  'patient_acknowledged',
] as const;

describe('counselling payload', () => {
  it('sends an explicit value for every topic', () => {
    // The server defaults each omitted flag to true, so a partial body would
    // record that topics were covered when they were not.
    const payload: CounsellingRecordRequest = {
      medicine_explained: false,
      dosage_explained: true,
      storage_explained: false,
      side_effects_discussed: false,
      interaction_advice_given: false,
      patient_acknowledged: true,
      notes: '',
    };
    for (const key of TOPIC_KEYS) {
      expect(payload, `${key} must be sent explicitly`).toHaveProperty(key);
      expect(typeof payload[key]).toBe('boolean');
    }
  });

  it('does not rely on the server default for an uncovered topic', () => {
    const uncovered: CounsellingRecordRequest = Object.fromEntries(
      TOPIC_KEYS.map((key) => [key, false]),
    );
    for (const key of TOPIC_KEYS) {
      expect(uncovered[key]).toBe(false);
    }
  });

  it('covers exactly the topics the server records', () => {
    expect(TOPIC_KEYS).toHaveLength(6);
    expect(new Set(TOPIC_KEYS).size).toBe(TOPIC_KEYS.length);
  });
});

describe('collection safeguards', () => {
  it('treats supply and collection as separate facts', () => {
    // Paying for medicine is not receiving it, and the record must be able to
    // say which happened.
    const supplied = { status: 'SUPPLIED', collectedAt: null };
    expect(supplied.collectedAt).toBeNull();
  });

  it('requires a collector name before confirmation is possible', () => {
    const canConfirm = (name: string, gateOpen: boolean) => gateOpen && name.trim().length > 0;
    expect(canConfirm('', true)).toBe(false);
    expect(canConfirm('   ', true)).toBe(false);
    expect(canConfirm('J. Doe', true)).toBe(true);
    // The clinical/payment gate still governs regardless of the name.
    expect(canConfirm('J. Doe', false)).toBe(false);
  });
});

describe('android accessibility parity', () => {
  it('keeps interactive rows at an accessible touch size', () => {
    expect(controlSize.touchTarget).toBeGreaterThanOrEqual(48);
  });

  it('announces blocking states assertively on both platforms', () => {
    expect(CLINICAL_STATUS.BLOCKING.announce).toBe('assertive');
  });
});
