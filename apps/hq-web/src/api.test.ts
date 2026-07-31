import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  activateCustomer,
  approveCustomer,
  approveCashMovement,
  beginCustomerReview,
  createCustomer,
  createInsurer,
  createStockTransfer,
  dispatchStockTransfer,
  loadSystemHealth,
  HQApiError,
  executeHQBusinessAction,
  formatMoney,
  loadApprovedUnpaidClaims,
  loadClaimsAwaitingDecision,
  loadGovernmentCatalogue,
  loadHQOverview,
  loadHQWorkspace,
  loadInsurers,
  loadStockTransfers,
  loadPosRegisters,
  loadPosDeviceHealth,
  probeEndpointHeartbeat,
  reactivateCustomer,
  receiveStockTransfer,
  setHQTenantContext,
  startCashExceptionReview,
  suspendCustomer,
  updateGovernmentCatalogueSelection,
  varianceNeedsExplanation,
} from './api.js';
import type { HQBusinessAction, HQWorkItem } from './api.js';

afterEach(() => {
  setHQTenantContext('');
  vi.unstubAllGlobals();
});

describe('loadSystemHealth', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /**
   * The indicator this feeds used to be the fixed words "System live" beside a
   * fixed green dot, checking nothing. These pin the four answers it can now
   * give, because the failure that matters is the one where a degraded backend
   * still reads as healthy.
   */
  it('reports live when the backend says ok', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), { status: 200 }),
    ));
    await expect(loadSystemHealth()).resolves.toBe('live');
  });

  it('reports degraded when the backend answers without an ok status', async () => {
    // Absence of a reported problem is not a reported healthy state.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ product: 'DawaTrace' }), { status: 200 }),
    ));
    await expect(loadSystemHealth()).resolves.toBe('degraded');
  });

  it('reports degraded on a non-ok response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })));
    await expect(loadSystemHealth()).resolves.toBe('degraded');
  });

  it('reports unreachable when the request throws', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')));
    await expect(loadSystemHealth()).resolves.toBe('unreachable');
  });

  it('calls an unreadable body degraded, not unreachable', async () => {
    // It answered; the answer was gibberish. Reporting "unreachable" would send
    // somebody to check the network instead of the server.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('not json', { status: 200 })));
    await expect(loadSystemHealth()).resolves.toBe('degraded');
  });
});

describe('heartbeat telemetry', () => {
  it('loads recorded POS device health from the authoritative endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), {
        headers: { 'Content-Type': 'application/json' },
        status: 200,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    setHQTenantContext('tenant-123');

    await loadPosDeviceHealth();

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/pos/dispensing/devices/',
      expect.objectContaining({
        headers: expect.objectContaining({ 'X-Tenant-ID': 'tenant-123' }),
      }),
    );
  });

  it('reports measured endpoint status instead of assuming online', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })));

    await expect(probeEndpointHeartbeat('/api/pricing/books/')).resolves.toMatchObject({
      endpoint: '/api/pricing/books/',
      status: 'DEGRADED',
      statusCode: 503,
    });
  });

  it('reports an endpoint offline when no response arrives', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')));

    await expect(probeEndpointHeartbeat('/api/health/')).resolves.toMatchObject({
      endpoint: '/api/health/',
      status: 'OFFLINE',
      statusCode: null,
    });
  });
});

describe('tenant-scoped directory writes', () => {
  it('sends tenant and CSRF context when creating an insurer', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'insurer-1' }), {
        headers: { 'Content-Type': 'application/json' },
        status: 201,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    setHQTenantContext('tenant-123');

    await createInsurer({
      code: 'SHA-KE',
      name: 'Social Health Authority Kenya',
      insurer_type: 'PUBLIC',
      integration_adapter: 'SHA',
      environment: 'SANDBOX',
    }, 'csrf-123');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/insurance/insurers/',
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-CSRFToken': 'csrf-123',
          'X-Tenant-ID': 'tenant-123',
        }),
        method: 'POST',
      }),
    );
  });

  it('sends tenant context for customer creation and governance actions', async () => {
    const fetchMock = vi.fn().mockImplementation(async () =>
      new Response(JSON.stringify({ id: 'customer-1', status: 'UNDER_REVIEW' }), {
        headers: { 'Content-Type': 'application/json' },
        status: 201,
      }));
    vi.stubGlobal('fetch', fetchMock);
    setHQTenantContext('tenant-123');

    await createCustomer({
      customer_number: 'CUST-001',
      legal_name: 'Nairobi Health Chemists Ltd',
      customer_type: 'PHARMACY',
    }, 'csrf-123');
    await beginCustomerReview('customer/1', 'Documents received', 'csrf-123');
    await approveCustomer('customer/1', 'Governance review passed', 'csrf-123');
    await activateCustomer('customer/1', 'Commercial account enabled', 'csrf-123');
    await suspendCustomer('customer/1', 'Licence expired', 'csrf-123');
    await reactivateCustomer('customer/1', 'Licence restored', 'csrf-123');

    for (const [, request] of fetchMock.mock.calls) {
      expect(request).toEqual(expect.objectContaining({
        headers: expect.objectContaining({
          'X-CSRFToken': 'csrf-123',
          'X-Tenant-ID': 'tenant-123',
        }),
        method: 'POST',
      }));
    }
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      '/api/customers/customers/customer%2F1/begin-review/',
    );
    expect(fetchMock.mock.calls[2]?.[0]).toBe(
      '/api/customers/customers/customer%2F1/approve/',
    );
    expect(fetchMock.mock.calls[3]?.[0]).toBe(
      '/api/customers/customers/customer%2F1/activate/',
    );
    expect(fetchMock.mock.calls[4]?.[0]).toBe(
      '/api/customers/customers/customer%2F1/suspend/',
    );
    expect(fetchMock.mock.calls[5]?.[0]).toBe(
      '/api/customers/customers/customer%2F1/reactivate/',
    );
  });
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

  it('sends the selected platform-admin tenant workspace', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        attention_items: [],
        data_summary: [],
        generated_at: '2026-07-29T09:00:00Z',
        is_platform_overview: false,
        metrics: [],
        network_items: [],
        scope_description: 'Tenant operations',
        scope_label: 'Tenant overview',
        tenant_id: 'tenant-123',
        tenant_name: 'Demo Pharmacy',
        user_name: 'HQ Admin',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);
    setHQTenantContext('tenant-123');

    await loadHQOverview();

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/hq/overview/',
      expect.objectContaining({
        headers: expect.objectContaining({ 'X-Tenant-ID': 'tenant-123' }),
      }),
    );
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
    expect((await loadInsurers('tenant-123')).length).toBe(2);
  });

  it('reads a paginated collection', async () => {
    // Turning pagination on is a presentation change and must not break the UI.
    respond({ results: [{ code: 'A' }] });
    expect((await loadInsurers('tenant-123')).length).toBe(1);
  });

  it('throws rather than returning an empty list on failure', async () => {
    // A section rendering "0 claims" because the request failed is worse than
    // one saying it could not load: the first is believed.
    respond(null, false, 503);
    await expect(loadApprovedUnpaidClaims('tenant-123')).rejects.toThrow(HQApiError);
  });

  it('keeps approved-unpaid and awaiting-decision as separate calls', async () => {
    const called: string[] = [];
    globalThis.fetch = (async (url: string) => {
      called.push(String(url));
      return { ok: true, status: 200, json: async () => [] } as unknown as Response;
    }) as typeof fetch;

    await loadApprovedUnpaidClaims('tenant-123');
    await loadClaimsAwaitingDecision('tenant-123');
    // Showing them together is how transport acceptance starts looking like a
    // debt.
    expect(called[0]).not.toBe(called[1]);
  });
});

describe('cash control routes', () => {
  it('loads registers from the authoritative POS shift namespace', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), {
        headers: { 'Content-Type': 'application/json' },
        status: 200,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    setHQTenantContext('tenant-123');

    await loadPosRegisters();

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/pos/shift/registers/',
      expect.objectContaining({
        headers: expect.objectContaining({ 'X-Tenant-ID': 'tenant-123' }),
      }),
    );
  });

  it('approves a movement through the POS shift route', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'movement-1' }), {
        headers: { 'Content-Type': 'application/json' },
        status: 200,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    setHQTenantContext('tenant-123');

    await approveCashMovement('movement-1', 'csrf-123');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/pos/shift/cash-movements/movement-1/approve/',
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-CSRFToken': 'csrf-123',
          'X-Tenant-ID': 'tenant-123',
        }),
        method: 'POST',
      }),
    );
  });

  it('starts exception review through the POS shift report route', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'review-1', status: 'UNDER_REVIEW' }), {
        headers: { 'Content-Type': 'application/json' },
        status: 200,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    setHQTenantContext('tenant-123');

    await startCashExceptionReview('report-1', 'Investigate till variance.', 'csrf-123');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/pos/shift/reports/report-1/start-cash-review/',
      expect.objectContaining({
        body: JSON.stringify({ note: 'Investigate till variance.' }),
        headers: expect.objectContaining({
          'X-CSRFToken': 'csrf-123',
          'X-Tenant-ID': 'tenant-123',
        }),
        method: 'POST',
      }),
    );
  });
});

describe('stock transfer routes', () => {
  it('loads transfers for the explicitly selected inventory tenant', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), {
        headers: { 'Content-Type': 'application/json' },
        status: 200,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await loadStockTransfers('tenant-stock');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/inventory/transfers/',
      expect.objectContaining({
        headers: expect.objectContaining({ 'X-Tenant-ID': 'tenant-stock' }),
      }),
    );
  });

  it('routes transfer request, dispatch, and receipt through governed actions', async () => {
    const fetchMock = vi.fn().mockImplementation(async () =>
      new Response(JSON.stringify({ id: 'transfer-1', status: 'SUBMITTED' }), {
        headers: { 'Content-Type': 'application/json' },
        status: 200,
      }));
    vi.stubGlobal('fetch', fetchMock);

    await createStockTransfer({
      destination_location: 'destination-1',
      document_reference: 'REQ-001',
      lines: [{ quantity: '2.0000', sku: 'sku-1' }],
      reason: 'Branch rebalance',
      source_location: 'source-1',
      transfer_number: 'TRF-001',
    }, 'tenant-stock', 'csrf-stock');
    await dispatchStockTransfer('transfer-1', 'tenant-stock', 'csrf-stock');
    await receiveStockTransfer('transfer-1', {
      idempotency_key: 'receipt-1',
      lines: [{
        batch_id: 'batch-1',
        damaged: '0',
        discrepancy_reason: '',
        line_id: 'line-1',
        quantity: '2.0000',
      }],
    }, 'tenant-stock', 'csrf-stock');

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      '/api/inventory/transfers/',
      '/api/inventory/transfers/transfer-1/dispatch/',
      '/api/inventory/transfers/transfer-1/receive/',
    ]);
    for (const [, request] of fetchMock.mock.calls) {
      expect(request).toEqual(expect.objectContaining({
        headers: expect.objectContaining({
          'X-CSRFToken': 'csrf-stock',
          'X-Tenant-ID': 'tenant-stock',
        }),
        method: 'POST',
      }));
    }
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

describe('loadGovernmentCatalogue', () => {
  it('builds the searchable government catalogue request', async () => {
    const payload = {
      available_keml_statuses: ['No', 'Yes'],
      available_levels_of_use: ['1', '2', '3', '4', '5', '6', '9'],
      catalogue_count: 11467,
      count: 1,
      page: 2,
      page_size: 50,
      pages: 1,
      results: [{ code: 'PH7839', generic_name: 'Diazepam' }],
      selected_count: 3,
      source: 'Kenya eTCD Product Catalogue',
      source_version: 'sha256:test;updated:2026-07-14',
      tenant_id: 'tenant-1',
      tenant_name: 'Demo Tenant',
      can_manage: true,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(loadGovernmentCatalogue({
      kemlStatus: 'Yes',
      levelOfUse: '4',
      page: 2,
      pageSize: 50,
      query: 'Diazepam',
      selectedOnly: true,
      tenantId: 'tenant-1',
    })).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/medicines/government-catalogue/?q=Diazepam&keml_status=Yes&level_of_use=4&selected_only=true&page=2&page_size=50',
      expect.objectContaining({
        credentials: 'include',
        headers: expect.objectContaining({ 'X-Tenant-ID': 'tenant-1' }),
      }),
    );
  });

  it('adds a master product to one tenant catalogue', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ selected: true }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(updateGovernmentCatalogueSelection(
      'medicine-1',
      true,
      'tenant-1',
      'csrf-1',
    )).resolves.toEqual({ selected: true });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/medicines/government-catalogue/medicine-1/selection/',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'X-CSRFToken': 'csrf-1',
          'X-Tenant-ID': 'tenant-1',
        }),
      }),
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

  it('flattens field-level domain validation for the action dialog', async () => {
    const action = {
      confirm: '',
      fields: [],
      key: 'hold-prescription',
      label: 'Place clinical hold',
      method: 'POST',
      path: '/api/prescriptions/prescription-1/hold/',
      tone: 'warning',
    } satisfies HQBusinessAction;
    const item = {
      actions: [action],
      detail: '',
      id: 'prescription-1',
      metrics: [],
      reference: 'RX-1',
      status: 'LEGALLY_VALIDATED',
      tenant_id: 'tenant-1',
      tenant_name: 'HQ Demo',
      title: 'Demo Patient',
    } satisfies HQWorkItem;
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ reason: ['A hold reason is required.'] }), {
          headers: { 'Content-Type': 'application/json' },
          status: 400,
        }),
      ),
    );

    await expect(
      executeHQBusinessAction(action, item, 'csrf-123', {}),
    ).rejects.toThrow('reason: A hold reason is required.');
  });

  it('expands dotted field names into nested service payloads', async () => {
    const action = {
      confirm: '',
      fields: [],
      key: 'receive-return',
      label: 'Receive return',
      method: 'POST',
      path: '/api/sales/returns/return-1/receive/',
      tone: 'primary',
    } satisfies HQBusinessAction;
    const item = {
      actions: [action],
      detail: '',
      id: 'return-1',
      metrics: [],
      reference: 'RTN-1',
      status: 'APPROVED',
      tenant_id: 'tenant-1',
      tenant_name: 'HQ Demo',
      title: 'Demo Pharmacy',
    } satisfies HQWorkItem;
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', {
        headers: { 'Content-Type': 'application/json' },
        status: 200,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await executeHQBusinessAction(
      action,
      item,
      'csrf-123',
      {
        'received_quantities.line-1': 2,
        'received_quantities.line-2': 1,
      },
    );

    expect(fetchMock).toHaveBeenCalledWith(
      action.path,
      expect.objectContaining({
        body: JSON.stringify({
          received_quantities: {
            'line-1': 2,
            'line-2': 1,
          },
        }),
      }),
    );
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
