/**
 * Wire format to domain model for clinical screening.
 *
 * The API client casts `response.json()` straight to the domain type. The
 * server is Django REST Framework and emits snake_case; the domain type is
 * camelCase. The cast therefore compiles cleanly and produces an object whose
 * every renamed field is `undefined` at runtime.
 *
 * For this particular payload that is not a cosmetic bug:
 *
 *   safe_to_proceed   -> safeToProceed      undefined, falsy, reads as unsafe
 *   blocking_findings -> blockingFindings   undefined, coerces to 0
 *
 * The first fails safe by luck. The second does not: a screening with three
 * blocking interactions would present as a screening with none. This module
 * exists so that reading never depends on that luck.
 *
 * The rule it enforces: the client never manufactures `safeToProceed`. It is
 * copied from the server's `safe_to_proceed` and only when that field is
 * literally `true`. A missing field, a null, a truthy string, or a response we
 * could not parse all mean "not safe", because none of them is the server
 * saying it is.
 */
import type { ClinicalSeverity, ClinicalScreeningStatus } from './types.js';

/** Raised when a screening response cannot be read as authoritative. */
export class UnreadableScreeningResponse extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'UnreadableScreeningResponse';
  }
}

export interface ScreeningFinding {
  readonly id: string;
  readonly category: string;
  readonly severity: ClinicalSeverity;
  readonly title: string;
  readonly explanation: string;
  readonly recommendation: string;
  readonly blocking: boolean;
  readonly requiresPharmacist: boolean;
  readonly overrideAllowed: boolean;
  readonly resolutionStatus: string;
}

export interface ScreeningDecision {
  readonly id: string;
  readonly findingId: string;
  readonly pharmacistName: string;
  readonly decision: string;
  readonly clinicalJustification: string;
  readonly conditions: string;
  readonly followUpActions: string;
  readonly ruleVersion: string;
  readonly createdAt: string;
}

export interface ScreeningResult {
  readonly screeningId: string;
  readonly contextHash: string;
  readonly findings: readonly ScreeningFinding[];
  readonly highestSeverity: ClinicalSeverity | null;
  readonly blockingCount: number;
  readonly requiresPharmacist: boolean;
  /** Strictly the server's answer. Never derived. */
  readonly safeToProceed: boolean;
  readonly screeningStatus: ClinicalScreeningStatus | '';
  readonly evaluatedAt: string;
  readonly ruleSetVersion: string;
  readonly decisions: readonly ScreeningDecision[];
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value);
}

function bool(value: unknown): boolean {
  // Deliberately strict. A truthy string is not a server assertion.
  return value === true;
}

function count(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : 0;
}

function mapFinding(raw: Record<string, unknown>): ScreeningFinding {
  return {
    id: text(raw['id']),
    category: text(raw['category']),
    severity: (text(raw['severity']) || 'INFORMATION') as ClinicalSeverity,
    title: text(raw['title']),
    explanation: text(raw['clinical_explanation'] ?? raw['summary']),
    recommendation: text(raw['recommendation']),
    blocking: bool(raw['blocking']),
    requiresPharmacist: bool(raw['requires_pharmacist']),
    overrideAllowed: bool(raw['override_allowed']),
    resolutionStatus: text(raw['resolution_status']),
  };
}

function mapDecision(raw: Record<string, unknown>): ScreeningDecision {
  return {
    id: text(raw['id']),
    findingId: text(raw['finding_id']),
    pharmacistName: text(raw['pharmacist_name']),
    decision: text(raw['decision']),
    clinicalJustification: text(raw['clinical_justification']),
    conditions: text(raw['conditions']),
    followUpActions: text(raw['follow_up_actions']),
    ruleVersion: text(raw['rule_version_at_decision']),
    createdAt: text(raw['created_at']),
  };
}

/**
 * Read a screening response.
 *
 * Throws rather than returning a degraded result when the payload is not an
 * object or carries no screening identifier: a screening we cannot identify is
 * one we cannot later acknowledge, override or audit, and presenting it as a
 * completed screening would be worse than reporting the failure.
 */
export function readScreeningResult(payload: unknown): ScreeningResult {
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new UnreadableScreeningResponse('Clinical screening response was not an object.');
  }
  const raw = payload as Record<string, unknown>;

  const screeningId = text(raw['screening_id'] ?? raw['id']);
  if (!screeningId) {
    throw new UnreadableScreeningResponse(
      'Clinical screening response carried no screening identifier.',
    );
  }

  const rawFindings = Array.isArray(raw['findings']) ? (raw['findings'] as unknown[]) : [];
  const findings = rawFindings
    .filter((f): f is Record<string, unknown> => f !== null && typeof f === 'object')
    .map(mapFinding);
  const decisions = (Array.isArray(raw['decisions']) ? raw['decisions'] : [])
    .filter((decision): decision is Record<string, unknown> => decision !== null && typeof decision === 'object')
    .map(mapDecision);

  // Prefer the server's own count. Fall back to counting the findings it sent
  // rather than to zero -- zero is the answer that lets a blocked basket
  // through.
  const declared = raw['blocking_findings'];
  const blockingCount =
    declared === undefined || declared === null
      ? findings.filter((f) => f.blocking).length
      : count(declared);

  return {
    screeningId,
    contextHash: text(raw['context_hash']),
    findings,
    highestSeverity: (text(raw['highest_severity']) || null) as ClinicalSeverity | null,
    blockingCount,
    requiresPharmacist: bool(raw['requires_pharmacist']),
    safeToProceed: bool(raw['safe_to_proceed']),
    screeningStatus: text(raw['status'] ?? raw['screening_status']) as ClinicalScreeningStatus | '',
    evaluatedAt: text(raw['evaluated_at']),
    ruleSetVersion: text(raw['rule_set_version']),
    decisions,
  };
}

/**
 * Whether the console may present this screening as permitting progression.
 *
 * Both conditions must hold. A server that says safe while also reporting a
 * blocking finding is self-contradictory, and the safe answer to a
 * contradiction is the restrictive one.
 */
export function permitsProgression(result: ScreeningResult): boolean {
  return result.safeToProceed && result.blockingCount === 0;
}
