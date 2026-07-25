import { describe, expect, it } from 'vitest';

import type { TimelineEntry } from './timeline.js';
import {
  TIMELINE_EVENTS,
  notableEntries,
  orderTimeline,
  toTimelineType,
} from './timeline.js';

function entry(overrides: Partial<TimelineEntry> = {}): TimelineEntry {
  return {
    id: 'e-1',
    type: 'PRESCRIPTION_LOADED',
    occurredAt: '2026-01-01T09:00:00Z',
    actor: 'A. Pharmacist',
    summary: 'Prescription loaded',
    ...overrides,
  };
}

describe('ordering', () => {
  it('reads oldest first', () => {
    const ordered = orderTimeline([
      entry({ id: 'b', occurredAt: '2026-01-01T10:00:00Z' }),
      entry({ id: 'a', occurredAt: '2026-01-01T09:00:00Z' }),
    ]);
    expect(ordered.map((e) => e.id)).toEqual(['a', 'b']);
  });

  it('is stable for events sharing a timestamp', () => {
    // An audit view that shuffles between renders is one nobody trusts.
    const same = '2026-01-01T09:00:00Z';
    const input = [
      entry({ id: 'first', occurredAt: same }),
      entry({ id: 'second', occurredAt: same }),
      entry({ id: 'third', occurredAt: same }),
    ];
    expect(orderTimeline(input).map((e) => e.id)).toEqual(['first', 'second', 'third']);
    expect(orderTimeline(input).map((e) => e.id)).toEqual(['first', 'second', 'third']);
  });

  it('does not drop entries with an unparseable timestamp', () => {
    // Losing an event would hide precisely what an investigation needs.
    const ordered = orderTimeline([
      entry({ id: 'good', occurredAt: '2026-01-01T09:00:00Z' }),
      entry({ id: 'bad', occurredAt: 'not-a-date' }),
    ]);
    expect(ordered).toHaveLength(2);
    expect(ordered.map((e) => e.id).sort()).toEqual(['bad', 'good']);
  });
});

describe('notability', () => {
  it('marks refusals, reversals and staleness as notable', () => {
    // Someone opening a timeline is usually looking for where it went wrong.
    for (const type of [
      'SCREENING_INVALIDATED',
      'PAYMENT_REVERSED',
      'OFFLINE_SYNC_CONFLICT',
      'CLINICAL_CONTEXT_STALE',
      'CAPABILITY_DENIED',
      'LABEL_REPRINTED',
    ] as const) {
      expect(TIMELINE_EVENTS[type].notable, type).toBe(true);
    }
  });

  it('does not make routine progress notable', () => {
    for (const type of [
      'PRESCRIPTION_LOADED',
      'MEDICINE_PREPARED',
      'PAYMENT_SETTLED',
      'MEDICINE_SUPPLIED',
    ] as const) {
      expect(TIMELINE_EVENTS[type].notable, type).toBe(false);
    }
  });

  it('separates an original print from a reprint', () => {
    expect(TIMELINE_EVENTS.LABEL_PRINTED.notable).toBe(false);
    expect(TIMELINE_EVENTS.LABEL_REPRINTED.notable).toBe(true);
  });

  it('filters to notable entries', () => {
    const entries = [
      entry({ id: 'routine', type: 'MEDICINE_PREPARED' }),
      entry({ id: 'problem', type: 'PAYMENT_REVERSED' }),
    ];
    expect(notableEntries(entries).map((e) => e.id)).toEqual(['problem']);
  });
});

describe('server event mapping', () => {
  it('maps server names onto the timeline vocabulary', () => {
    expect(toTimelineType('DISPENSING_PAYMENT_PROCESSED')).toBe('PAYMENT_SETTLED');
    expect(toTimelineType('OVERRIDE_RECORDED')).toBe('OVERRIDE_APPROVED');
    expect(toTimelineType('FINDING_RESOLVED')).toBe('PHARMACIST_DECISION_RECORDED');
  });

  it('passes through names that already match', () => {
    expect(toTimelineType('MEDICINE_SUPPLIED')).toBe('MEDICINE_SUPPLIED');
  });

  it('returns null for an unrecognised event rather than guessing', () => {
    // Rendering an unknown event as something familiar would misreport history.
    expect(toTimelineType('SOME_FUTURE_EVENT')).toBeNull();
  });

  it('gives every declared type a presentation', () => {
    for (const [type, presentation] of Object.entries(TIMELINE_EVENTS)) {
      expect(presentation.label.length, type).toBeGreaterThan(0);
      expect(presentation.status.length, type).toBeGreaterThan(0);
    }
  });
});
