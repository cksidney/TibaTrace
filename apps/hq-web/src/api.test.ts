import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  HQApiError,
  executeHQBusinessAction,
  formatMoney,
  loadApprovedUnpaidClaims,
  loadClaimsAwaitingDecision,
  loadHQOverview,
  loadHQWorkspace,
  loadInsurers,
  varianceNeedsExplanation,
} from './api.js';
import type { HQBusinessAction, HQWorkItem } from './api.js';

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

describe('loadHQWorkspace', () => {
  it('loads the cross-domain HQ workspace with the authenticated session', async () => {
    const payload = {
      business_modules: [],
      generated_at: '2026-07-26T12:00:00Z',
      people: { counts: {}, customers: [], patients: [], practitioners: [] },
      catalogue: { counts: {}, skus: [] },
      commerce: { counts: {}, dispatches: [], orders: [] },
      governance: { counts: {}, audit_events: [], crosswalks: [], documents: [], domain_events: [], notifications: [] },
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(loadHQWorkspace()).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/hq/workspace/',
      expect.objectContaining({ credentials: 'include' }),
    );
  });
});

describe('executeHQBusinessAction', () => {
  it('posts the action with CSRF and tenant context', async () => {
    const action: HQBusinessAction = {
      confirm: 'Approve this customer?',
      fields: [],
      key: 'approve-customer',
      label: 'Approve customer',
      method: 'POST',
      path: '/api/customers/customers/customer-1/approve/',
      tone: 'primary',
    };
    const item: HQWorkItem = {
      actions: [action],
      detail: 'Pharmacy',
      id: 'customer-1',
      metrics: [],
      reference: 'CUS-001',
      status: 'PROSPECTIVE',
      tenant_id: 'tenant-1',
      tenant_name: 'HQ Demo',
      title: 'Demo Pharmacy',
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'approved' }), {
        headers: { 'Content-Type': 'application/json' },
        status: 200,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      executeHQBusinessAction(action, item, 'csrf-123', { reason: 'Verified' }),
    ).resolves.toEqual({ status: 'approved' });
    expect(fetchMock).toHaveBeenCalledWith(
      action.path,
      expect.objectContaining({
        body: JSON.stringify({ reason: 'Verified' }),
        credentials: 'include',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          'X-CSRFToken': 'csrf-123',
          'X-Tenant-ID': 'tenant-1',
        }),
        method: 'POST',
      }),
    );
  });

  it('surfaces the service error message', async () => {
    const action = {
      confirm: '',
      fields: [],
      key: 'release-batch',
      label: 'Release batch',
      method: 'POST',
      path: '/api/procurement/received-batches/batch-1/release/',
      tone: 'primary',
    } satisfies HQBusinessAction;
    const item = {
      actions: [action],
      detail: '',
      id: 'batch-1',
      metrics: [],
      reference: 'B-1',
      status: 'QUARANTINED',
      tenant_id: 'tenant-1',
      tenant_name: 'HQ Demo',
      title: 'Demo medicine',
    } satisfies HQWorkItem;
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: 'Inspection is incomplete.' }), {
          headers: { 'Content-Type': 'application/json' },
          status: 400,
        }),
      ),
    );

    await expect(
      executeHQBusinessAction(action, item, 'csrf-123', {}),
    ).rejects.toThrow('Inspection is incomplete.');
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
