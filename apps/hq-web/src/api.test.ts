import { afterEach, describe, expect, it, vi } from 'vitest';

import { HQApiError, formatMoney, loadApprovedUnpaidClaims, loadClaimsAwaitingDecision, loadHQOverview, loadInsurers, varianceNeedsExplanation } from './api.js';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('loadHQOverview', () => {
  it('loads authenticated HQ data with same-origin credentials', async () => {
    const payload = {
      attention_items: [],
      data_summary: [],
      generated_at: '2026-07-26T09:00:00Z',
      is_platform_overview: true,
      metrics: [],
      network_items: [],
      scope_description: 'All operations',
      scope_label: 'Platform overview',
      tenant_id: '',
      tenant_name: 'All tenants',
      user_name: 'HQ Admin',
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(loadHQOverview()).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/hq/overview/',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  it('surfaces authentication failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 403 })));

    await expect(loadHQOverview()).rejects.toMatchObject({ status: 403 });
  });
});

describe('workbench collections', () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function respond(body: unknown, ok = true, status = 200) {
    globalThis.fetch = (async () =>
      ({ ok, status, json: async () => body }) as unknown as Response) as typeof fetch;
  }

  it('reads an unpaginated collection', async () => {
    respond([{ code: 'A' }, { code: 'B' }]);
    expect((await loadInsurers()).length).toBe(2);
  });

  it('reads a paginated collection', async () => {
    // Turning pagination on is a presentation change and must not break the UI.
    respond({ results: [{ code: 'A' }] });
    expect((await loadInsurers()).length).toBe(1);
  });

  it('throws rather than returning an empty list on failure', async () => {
    // A section rendering "0 claims" because the request failed is worse than
    // one saying it could not load: the first is believed.
    respond(null, false, 503);
    await expect(loadApprovedUnpaidClaims()).rejects.toThrow(HQApiError);
  });

  it('keeps approved-unpaid and awaiting-decision as separate calls', async () => {
    const called: string[] = [];
    globalThis.fetch = (async (url: string) => {
      called.push(String(url));
      return { ok: true, status: 200, json: async () => [] } as unknown as Response;
    }) as typeof fetch;

    await loadApprovedUnpaidClaims();
    await loadClaimsAwaitingDecision();
    // Showing them together is how transport acceptance starts looking like a
    // debt.
    expect(called[0]).not.toBe(called[1]);
  });
});

describe('formatMoney', () => {
  it('formats a decimal string without a float round trip', () => {
    expect(formatMoney('22000.00')).toBe('KES 22,000.00');
  });

  it('does not lose precision that Number() would', () => {
    // Number('9007199254740993.01') cannot represent this exactly.
    expect(formatMoney('9007199254740993.01')).toBe('KES 9,007,199,254,740,993.01');
  });

  it('renders a missing amount as a dash rather than zero', () => {
    // Zero is a price. Absent is not.
    expect(formatMoney(null)).toBe('—');
    expect(formatMoney(undefined)).toBe('—');
    expect(formatMoney('')).toBe('—');
  });

  it('never renders NaN onto a money field', () => {
    // Number('abc').toFixed(2) gives "NaN", which then appears as an amount.
    expect(formatMoney('not-a-number')).toBe('—');
    expect(formatMoney('12.3.4')).toBe('—');
  });

  it('formats a negative amount', () => {
    expect(formatMoney('-50.00')).toBe('KES -50.00');
  });

  it('pads a short fraction', () => {
    expect(formatMoney('600.5')).toBe('KES 600.50');
  });

  it('handles a whole number', () => {
    expect(formatMoney('600')).toBe('KES 600.00');
  });
});

describe('varianceNeedsExplanation', () => {
  it('reads the signed snapshot rather than recomputing', () => {
    const report = {
      snapshot: { variance: { requires_explanation: true, classification: 'SHORT' } },
    } as never;
    expect(varianceNeedsExplanation(report)).toBe(true);
  });

  it('is false when a report has no variance', () => {
    expect(varianceNeedsExplanation({ snapshot: { variance: null } } as never)).toBe(false);
  });

  it('is false when a report has no snapshot at all', () => {
    expect(varianceNeedsExplanation({} as never)).toBe(false);
  });
});
