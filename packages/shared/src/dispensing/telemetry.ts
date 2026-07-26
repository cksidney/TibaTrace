/**
 * Operational telemetry for the POS clients.
 *
 * Telemetry is the easiest place in a clinical system to leak patient data by
 * accident: someone adds "just the medicine name" to a latency metric and it
 * ends up in a log aggregator with a different retention policy and a wider
 * audience than the clinical record ever had.
 *
 * So this module is built to make that hard rather than to rely on care. Events
 * carry a fixed set of numeric and enumerated fields; free text and identifiers
 * are dropped by the sanitiser rather than trusted not to appear.
 */

export type TelemetryEvent =
  | 'SCREEN_LOAD_FAILED'
  | 'CLINICAL_SCREENING_LATENCY'
  | 'PAYMENT_CONFIRMATION_LATENCY'
  | 'OFFLINE_PACKAGE_REJECTED'
  | 'STALE_CONTEXT_ENCOUNTERED'
  | 'BARCODE_VALIDATION_FAILED'
  | 'WORKFLOW_ABANDONED'
  | 'TASK_WAITING_TIME'
  | 'UI_ERROR_BOUNDARY'
  | 'OFFLINE_QUEUE_RECONCILIATION';

/** Fields a telemetry event may carry. Anything else is discarded. */
export interface TelemetryPayload {
  /** Milliseconds, for latency events. */
  readonly durationMs?: number;
  /** A count, never an identifier. */
  readonly count?: number;
  /** Enumerated outcome, never free text. */
  readonly outcome?: 'SUCCESS' | 'FAILURE' | 'TIMEOUT' | 'BLOCKED' | 'UNKNOWN';
  /** A typed error code from the shared contract, never a message. */
  readonly code?: string;
  /** Which workflow stage, for abandonment analysis. */
  readonly stage?: string;
  /** Which screen, for error boundaries. */
  readonly screen?: string;
}

export interface TelemetryRecord {
  readonly event: TelemetryEvent;
  readonly payload: TelemetryPayload;
  readonly occurredAt: string;
  /** Tenant and branch only. Never a patient, prescription or episode. */
  readonly tenantId: string;
  readonly branchId: string;
  readonly deviceId: string;
}

/**
 * Keys that will never be emitted, whatever a caller passes.
 *
 * An allowlist governs what survives; this list exists so an attempt to send
 * one of these is visible in review rather than silently stripped.
 */
const FORBIDDEN_KEYS: readonly string[] = [
  'patientId',
  'patientName',
  'patient',
  'prescriptionId',
  'prescription',
  'episodeId',
  'dispensingNumber',
  'medicine',
  'medicineName',
  'dosage',
  'batchNumber',
  'collectorName',
  'notes',
  'reason',
  'message',
  'justification',
  'idempotencyKey',
  'token',
  'signature',
];

const ALLOWED_KEYS: readonly (keyof TelemetryPayload)[] = [
  'durationMs',
  'count',
  'outcome',
  'code',
  'stage',
  'screen',
];

/**
 * Reduce an arbitrary object to the fields telemetry may carry.
 *
 * Allowlist rather than blocklist: a new field added to a caller's payload is
 * dropped by default, instead of shipping until someone notices.
 */
export function sanitisePayload(input: Record<string, unknown>): TelemetryPayload {
  const output: Record<string, unknown> = {};
  for (const key of ALLOWED_KEYS) {
    const value = input[key];
    if (value === undefined || value === null) continue;
    if (key === 'durationMs' || key === 'count') {
      if (typeof value === 'number' && Number.isFinite(value)) output[key] = Math.round(value);
      continue;
    }
    if (typeof value === 'string') {
      // Bounded so a stray identifier cannot ride along inside an enum field.
      output[key] = value.slice(0, 64);
    }
  }
  return output as TelemetryPayload;
}

/** True when a payload contains something that must never be emitted. */
export function containsForbiddenField(input: Record<string, unknown>): string | null {
  for (const key of Object.keys(input)) {
    if (FORBIDDEN_KEYS.includes(key)) return key;
  }
  return null;
}

export interface TelemetrySink {
  emit(record: TelemetryRecord): void;
}

export class Telemetry {
  private readonly sink: TelemetrySink;
  private readonly tenantId: string;
  private readonly branchId: string;
  private readonly deviceId: string;

  constructor(options: {
    sink: TelemetrySink;
    tenantId: string;
    branchId: string;
    deviceId: string;
  }) {
    this.sink = options.sink;
    this.tenantId = options.tenantId;
    this.branchId = options.branchId;
    this.deviceId = options.deviceId;
  }

  record(event: TelemetryEvent, payload: Record<string, unknown> = {}): TelemetryRecord {
    const record: TelemetryRecord = {
      event,
      payload: sanitisePayload(payload),
      occurredAt: new Date().toISOString(),
      tenantId: this.tenantId,
      branchId: this.branchId,
      deviceId: this.deviceId,
    };
    this.sink.emit(record);
    return record;
  }

  /** Time an operation and record its latency and outcome, never its content. */
  async time<T>(event: TelemetryEvent, operation: () => Promise<T>): Promise<T> {
    const started = Date.now();
    try {
      const result = await operation();
      this.record(event, { durationMs: Date.now() - started, outcome: 'SUCCESS' });
      return result;
    } catch (error) {
      // Only a typed code is emitted. An exception message may quote a patient
      // name or a medicine straight out of a server error.
      const code =
        typeof error === 'object' && error !== null && 'code' in error
          ? String((error as { code: unknown }).code)
          : 'UNKNOWN';
      this.record(event, { durationMs: Date.now() - started, outcome: 'FAILURE', code });
      throw error;
    }
  }
}
