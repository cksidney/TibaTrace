import { describe, expect, it, vi } from 'vitest';

import type { TelemetryRecord } from './telemetry.js';
import { Telemetry, containsForbiddenField, sanitisePayload } from './telemetry.js';

function collector() {
  const records: TelemetryRecord[] = [];
  return { records, emit: (record: TelemetryRecord) => records.push(record) };
}

function telemetry(sink: { emit: (r: TelemetryRecord) => void }) {
  return new Telemetry({ sink, tenantId: 'tenant-1', branchId: 'branch-1', deviceId: 'TILL-1' });
}

describe('payload sanitisation', () => {
  it('drops patient and clinical identifiers', () => {
    // Telemetry reaches a log aggregator with wider access and a different
    // retention policy than the clinical record ever had.
    const clean = sanitisePayload({
      durationMs: 120,
      patientId: 'pat-1',
      patientName: 'Grace Kamau',
      medicineName: 'Warfarin 5mg',
      prescriptionId: 'rx-1',
      episodeId: 'ep-1',
    });
    expect(clean).toEqual({ durationMs: 120 });
  });

  it('drops free text that could quote clinical content', () => {
    const clean = sanitisePayload({
      outcome: 'FAILURE',
      notes: 'Patient allergic to penicillin',
      reason: 'Severe interaction with warfarin',
      message: 'Blocked: Grace Kamau',
    });
    expect(clean).toEqual({ outcome: 'FAILURE' });
  });

  it('drops secrets', () => {
    const clean = sanitisePayload({ token: 'abc', signature: 'def', idempotencyKey: 'pay-1' });
    expect(clean).toEqual({});
  });

  it('uses an allowlist so a newly added field does not ship by default', () => {
    const clean = sanitisePayload({ count: 3, someFutureField: 'leaked' });
    expect(clean).toEqual({ count: 3 });
    expect(Object.keys(clean)).not.toContain('someFutureField');
  });

  it('bounds string fields so an identifier cannot ride along', () => {
    const clean = sanitisePayload({ code: 'X'.repeat(500) });
    expect(clean.code?.length).toBe(64);
  });

  it('rejects non-finite numbers', () => {
    expect(sanitisePayload({ durationMs: Number.NaN })).toEqual({});
    expect(sanitisePayload({ durationMs: Number.POSITIVE_INFINITY })).toEqual({});
  });

  it('rounds durations to whole milliseconds', () => {
    expect(sanitisePayload({ durationMs: 12.7 })).toEqual({ durationMs: 13 });
  });
});

describe('forbidden field detection', () => {
  it('names the offending field so review can catch it', () => {
    expect(containsForbiddenField({ patientName: 'x' })).toBe('patientName');
    expect(containsForbiddenField({ durationMs: 1 })).toBeNull();
  });
});

describe('emitted records', () => {
  it('carries tenant, branch and device but no episode', () => {
    const sink = collector();
    telemetry(sink).record('CLINICAL_SCREENING_LATENCY', { durationMs: 50 });

    const record = sink.records[0];
    expect(record?.tenantId).toBe('tenant-1');
    expect(record?.branchId).toBe('branch-1');
    expect(record?.deviceId).toBe('TILL-1');
    expect(JSON.stringify(record)).not.toContain('episode');
  });

  it('never emits a clinical identifier even when one is passed', () => {
    const sink = collector();
    telemetry(sink).record('STALE_CONTEXT_ENCOUNTERED', {
      patientId: 'pat-1',
      dispensingNumber: 'DISP-1',
      outcome: 'BLOCKED',
    });

    const serialised = JSON.stringify(sink.records[0]);
    expect(serialised).not.toContain('pat-1');
    expect(serialised).not.toContain('DISP-1');
    expect(sink.records[0]?.payload.outcome).toBe('BLOCKED');
  });
});

describe('timing', () => {
  it('records latency and success without the result', async () => {
    const sink = collector();
    const result = await telemetry(sink).time('PAYMENT_CONFIRMATION_LATENCY', async () => ({
      patientName: 'Grace Kamau',
    }));

    expect(result.patientName).toBe('Grace Kamau');
    expect(sink.records[0]?.payload.outcome).toBe('SUCCESS');
    expect(JSON.stringify(sink.records[0])).not.toContain('Grace');
  });

  it('records a typed code on failure, never the exception message', async () => {
    // A server error message may quote a patient name or medicine directly.
    const sink = collector();
    const failing = async () => {
      const error = Object.assign(new Error('Blocked: Grace Kamau allergic to penicillin'), {
        code: 'BLOCKING_FINDINGS',
      });
      throw error;
    };

    await expect(telemetry(sink).time('CLINICAL_SCREENING_LATENCY', failing)).rejects.toThrow();

    const record = sink.records[0];
    expect(record?.payload.outcome).toBe('FAILURE');
    expect(record?.payload.code).toBe('BLOCKING_FINDINGS');
    expect(JSON.stringify(record)).not.toContain('Grace');
    expect(JSON.stringify(record)).not.toContain('penicillin');
  });

  it('rethrows so telemetry never swallows a failure', async () => {
    const sink = collector();
    const spy = vi.fn(async () => {
      throw new Error('boom');
    });
    await expect(telemetry(sink).time('UI_ERROR_BOUNDARY', spy)).rejects.toThrow('boom');
    expect(spy).toHaveBeenCalledOnce();
  });
});
