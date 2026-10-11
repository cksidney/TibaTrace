import { describe, expect, it } from 'vitest';

import { PosRetailClient } from './client.js';

describe('PosRetailClient', () => {
  it('rehydrates a retail transaction without a request body', async () => {
    const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
      expect(String(input)).toBe('/api/pos/retail/transactions/transaction-1/');
      expect(init?.method).toBe('GET');
      expect(init?.body).toBeUndefined();
      return new Response(JSON.stringify({ id: 'transaction-1' }), { status: 200 });
    };
    const client = new PosRetailClient('/api/pos/retail', { fetcher: fetcher as typeof fetch });

    await expect(client.getTransaction('transaction-1')).resolves.toEqual({ id: 'transaction-1' });
  });

  it('settles retail checkout through the cash-only endpoint with a stable idempotency key', async () => {
    const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
      expect(String(input)).toBe('/api/pos/retail/transactions/transaction-1/cash-settle/');
      expect(init?.method).toBe('POST');
      expect(JSON.parse(String(init?.body))).toEqual({
        device_id: 'POS-01',
        cash_received: '150.00',
        idempotency_key: 'retail-cash-transaction-1',
        tender_type: 'CASH',
      });
      return new Response(JSON.stringify({ id: 'transaction-1', state: 'COMPLETED' }), { status: 200 });
    };
    const client = new PosRetailClient('/api/pos/retail', { fetcher: fetcher as typeof fetch });

    await expect(
      client.settleCash('transaction-1', {
        device_id: 'POS-01',
        cash_received: '150.00',
        idempotency_key: 'retail-cash-transaction-1',
      }),
    ).resolves.toMatchObject({ state: 'COMPLETED' });
  });
});
