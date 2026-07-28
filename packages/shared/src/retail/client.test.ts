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
});
