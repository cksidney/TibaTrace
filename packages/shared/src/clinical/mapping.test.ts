import { describe, expect, it } from 'vitest';

import {
  UnreadableScreeningResponse,
  permitsProgression,
  readScreeningResult,
} from './mapping.js';

/**
 * These pin the boundary between what the server said and what the console
 * shows.
 *
 * The API client casts `response.json()` straight to the camelCase domain type
 * while DRF emits snake_case, so `safeToProceed` and `blockingFindings` were
 * both `undefined` at runtime. The first failed safe by accident; the second
 * meant a basket with three blocking interactions presented as having none.
 *
 * Do not relax these. In particular, do not make `safeToProceed` truthy-tolerant
 * to accommodate a provider that sends "true" as a string -- fix the provider.
 */

// The shape DRF actually emits, from PosClinicalScreeningResultSerializer.
function serverResponse(overrides: Record<string, unknown> = {}) {
  return {
    id: 'row-1',
    screening_id: 'scr-1',
    context_hash: 'abc123',
    status: 'COMPLETE',
    highest_severity: null,
    blocking_findings: 0,
    requires_pharmacist: false,
    safe_to_proceed: true,
    evaluated_at: '2026-01-01T09:00:00Z',
    rule_set_version: '1.0',
    findings: [],
    ...overrides,
  };
}

function blockingFinding(overrides: Record<string, unknown> = {}) {
  return {
    id: 'f-1',
    category: 'DRUG_DRUG_INTERACTION',
    severity: 'CRITICAL',
    title: 'Drug-Drug Interaction: WARFARIN and ASPIRIN',
    clinical_explanation: 'Markedly increased bleeding risk.',
    recommendation: 'Contact the prescriber before supplying.',
    blocking: true,
    requires_pharmacist: true,
    override_allowed: false,
    ...overrides,
  };
}

describe('reading the server shape', () => {
  it('reads snake_case fields the raw cast silently dropped', () => {
    const result = readScreeningResult(serverResponse());
    expect(result.screeningId).toBe('scr-1');
    expect(result.contextHash).toBe('abc123');
    expect(result.safeToProceed).toBe(true);
    expect(result.evaluatedAt).toBe('2026-01-01T09:00:00Z');
  });

  it('reads the blocking count rather than losing it', () => {
    // The regression: this was undefined, coercing to 0.
    const result = readScreeningResult(
      serverResponse({ blocking_findings: 3, safe_to_proceed: false }),
    );
    expect(result.blockingCount).toBe(3);
  });

  it('maps finding detail including the interaction category', () => {
    const result = readScreeningResult(
      serverResponse({ blocking_findings: 1, safe_to_proceed: false, findings: [blockingFinding()] }),
    );
    const finding = result.findings[0];
    expect(finding?.category).toBe('DRUG_DRUG_INTERACTION');
    expect(finding?.blocking).toBe(true);
    expect(finding?.explanation).toContain('bleeding risk');
    expect(finding?.recommendation).toContain('prescriber');
    expect(finding?.overrideAllowed).toBe(false);
  });

  it('falls back to counting findings, never to zero', () => {
    // A server that omits the count must not read as "nothing blocking".
    const result = readScreeningResult(
      serverResponse({
        blocking_findings: undefined,
        safe_to_proceed: false,
        findings: [blockingFinding(), blockingFinding({ id: 'f-2' })],
      }),
    );
    expect(result.blockingCount).toBe(2);
  });
});

describe('safeToProceed is never manufactured', () => {
  it('is true only when the server says exactly true', () => {
    expect(readScreeningResult(serverResponse({ safe_to_proceed: true })).safeToProceed).toBe(true);
  });

  it.each([undefined, null, false, 0, '', 'true', 'yes', 1, {}])(
    'treats %p as not safe',
    (value) => {
      expect(
        readScreeningResult(serverResponse({ safe_to_proceed: value })).safeToProceed,
      ).toBe(false);
    },
  );

  it('does not infer safety from an absence of findings', () => {
    const result = readScreeningResult(
      serverResponse({ safe_to_proceed: false, blocking_findings: 0, findings: [] }),
    );
    expect(result.safeToProceed).toBe(false);
    expect(permitsProgression(result)).toBe(false);
  });
});

describe('progression', () => {
  it('permits progression only when safe and unblocked', () => {
    expect(permitsProgression(readScreeningResult(serverResponse()))).toBe(true);
  });

  it('refuses a self-contradictory response', () => {
    // Safe, yet reporting a blocker. The restrictive reading wins.
    const result = readScreeningResult(
      serverResponse({ safe_to_proceed: true, blocking_findings: 1, findings: [blockingFinding()] }),
    );
    expect(result.safeToProceed).toBe(true);
    expect(permitsProgression(result)).toBe(false);
  });
});

describe('unreadable responses', () => {
  it.each([null, undefined, 'a string', 42, []])('refuses %p', (payload) => {
    expect(() => readScreeningResult(payload)).toThrow(UnreadableScreeningResponse);
  });

  it('refuses a response with no screening identifier', () => {
    // Unidentifiable means it can never be acknowledged, overridden or audited.
    expect(() => readScreeningResult(serverResponse({ id: '', screening_id: '' }))).toThrow(
      UnreadableScreeningResponse,
    );
  });

  it('tolerates a malformed finding without dropping the screening', () => {
    const result = readScreeningResult(
      serverResponse({ blocking_findings: 1, safe_to_proceed: false, findings: [null, 'junk'] }),
    );
    expect(result.findings).toEqual([]);
    // The declared count still stands, so the basket stays blocked.
    expect(result.blockingCount).toBe(1);
    expect(permitsProgression(result)).toBe(false);
  });
});
