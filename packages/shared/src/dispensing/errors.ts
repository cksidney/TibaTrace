/**
 * Typed error contracts shared by the Windows and Android POS clients.
 *
 * Both clients must react to the same codes. A client that invents its own
 * interpretation of a failure ends up deciding clinical policy locally, which
 * is exactly what these contracts exist to prevent.
 */

export type PosErrorCode =
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'STALE_CLINICAL_CONTEXT'
  | 'SCREENING_REQUIRED'
  | 'BLOCKING_FINDINGS'
  | 'PHARMACIST_REVIEW_REQUIRED'
  | 'OVERRIDE_NOT_ALLOWED'
  | 'OVERRIDE_EXPIRED'
  | 'INVALID_OFFLINE_PACKAGE'
  | 'OFFLINE_PACKAGE_EXPIRED'
  | 'OFFLINE_NOT_PERMITTED'
  | 'SERVICE_UNAVAILABLE'
  | 'VALIDATION_ERROR'
  | 'CONFLICT'
  | 'NETWORK_UNAVAILABLE'
  | 'UNKNOWN';

export class PosApiError extends Error {
  readonly code: PosErrorCode;
  readonly status: number;
  readonly detail: unknown;

  constructor(code: PosErrorCode, message: string, status = 0, detail: unknown = null) {
    super(message);
    this.name = 'PosApiError';
    this.code = code;
    this.status = status;
    this.detail = detail;
  }

  /**
   * True when the caller may safely retry with the same idempotency key.
   *
   * Deliberately excludes CONFLICT and every clinical refusal: retrying those
   * cannot change the answer, and looping on them would hammer the server while
   * hiding a real blocker from the operator.
   */
  get retryable(): boolean {
    return this.code === 'SERVICE_UNAVAILABLE' || this.code === 'NETWORK_UNAVAILABLE';
  }

  /** True when the operator must resolve something clinical before proceeding. */
  get clinicallyBlocking(): boolean {
    return (
      this.code === 'STALE_CLINICAL_CONTEXT' ||
      this.code === 'SCREENING_REQUIRED' ||
      this.code === 'BLOCKING_FINDINGS' ||
      this.code === 'PHARMACIST_REVIEW_REQUIRED' ||
      this.code === 'OVERRIDE_NOT_ALLOWED' ||
      this.code === 'OVERRIDE_EXPIRED'
    );
  }
}

/** Map an HTTP status and body onto a typed code. Never guesses success. */
export function classifyError(status: number, body: unknown): PosApiError {
  const detail = extractDetail(body);
  const declared = extractCode(body);
  if (declared) {
    return new PosApiError(declared, detail || declared, status, body);
  }

  switch (status) {
    case 401:
      return new PosApiError('UNAUTHENTICATED', detail || 'Sign-in required.', status, body);
    case 403:
      return new PosApiError('FORBIDDEN', detail || 'Not permitted.', status, body);
    case 400:
      return new PosApiError('VALIDATION_ERROR', detail || 'Invalid request.', status, body);
    case 409:
      return new PosApiError('CONFLICT', detail || 'Conflicting state.', status, body);
    case 502:
    case 503:
    case 504:
      return new PosApiError('SERVICE_UNAVAILABLE', detail || 'Service unavailable.', status, body);
    default:
      return new PosApiError('UNKNOWN', detail || `Request failed (${status}).`, status, body);
  }
}

const KNOWN_CODES = new Set<string>([
  'UNAUTHENTICATED',
  'FORBIDDEN',
  'STALE_CLINICAL_CONTEXT',
  'SCREENING_REQUIRED',
  'BLOCKING_FINDINGS',
  'PHARMACIST_REVIEW_REQUIRED',
  'OVERRIDE_NOT_ALLOWED',
  'OVERRIDE_EXPIRED',
  'INVALID_OFFLINE_PACKAGE',
  'OFFLINE_PACKAGE_EXPIRED',
  'OFFLINE_NOT_PERMITTED',
  'SERVICE_UNAVAILABLE',
  'VALIDATION_ERROR',
  'CONFLICT',
]);

function extractCode(body: unknown): PosErrorCode | null {
  if (!body || typeof body !== 'object') return null;
  const record = body as Record<string, unknown>;
  const raw = record['code'] ?? record['error_code'];
  if (typeof raw === 'string' && KNOWN_CODES.has(raw)) {
    return raw as PosErrorCode;
  }
  // The dispensing API returns domain refusals as {"error": "..."}; recognise
  // the stale-context marker wherever it appears rather than losing it to
  // a generic 400.
  const message = record['error'] ?? record['detail'];
  if (typeof message === 'string' && message.includes('STALE_CLINICAL_CONTEXT')) {
    return 'STALE_CLINICAL_CONTEXT';
  }
  return null;
}

function extractDetail(body: unknown): string {
  if (typeof body === 'string') return body;
  if (!body || typeof body !== 'object') return '';
  const record = body as Record<string, unknown>;
  for (const key of ['error', 'detail', 'message']) {
    const value = record[key];
    if (typeof value === 'string') return value;
  }
  return '';
}
