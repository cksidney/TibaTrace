import { describe, expect, it } from 'vitest';

import { PosApiSession, PosAuthenticationError } from './session.js';
import type { PosSessionStorage, PosSessionTokens } from './session.js';

class MemoryStorage implements PosSessionStorage {
  value: PosSessionTokens | null = null;

  async load() {
    return this.value;
  }

  async save(tokens: PosSessionTokens) {
    this.value = tokens;
  }

  async clear() {
    this.value = null;
  }
}

const initial: PosSessionTokens = {
  access: 'access-1',
  refresh: 'refresh-1',
  tenantId: 'tenant-1',
  userId: 'user-1',
};

describe('PosApiSession', () => {
  it('persists login and injects bearer and tenant headers', async () => {
    const storage = new MemoryStorage();
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const fetcher: typeof fetch = async (input, init) => {
      calls.push({ url: String(input), ...(init ? { init } : {}) });
      if (String(input).endsWith('/api/identity/token/')) {
        return Response.json({
          access: initial.access,
          refresh: initial.refresh,
          tenant_id: initial.tenantId,
          user_id: initial.userId,
        });
      }
      return Response.json({ ok: true });
    };
    const session = new PosApiSession({
      baseUrl: 'https://tibatrace.example/',
      storage,
      fetcher,
    });

    await session.login('cashier', 'secret');
    await session.fetch('/api/pos/dispensing/episodes/queue/');

    expect(storage.value).toEqual(initial);
    expect(calls[1]?.url).toBe(
      'https://tibatrace.example/api/pos/dispensing/episodes/queue/',
    );
    const headers = new Headers(calls[1]?.init?.headers);
    expect(headers.get('Authorization')).toBe('Bearer access-1');
    expect(headers.get('X-Tenant-ID')).toBe('tenant-1');
  });

  it('refreshes once after a 401 and retries the request', async () => {
    const storage = new MemoryStorage();
    storage.value = initial;
    let protectedCalls = 0;
    const fetcher: typeof fetch = async (input, init) => {
      if (String(input).endsWith('/api/identity/token/refresh/')) {
        return Response.json({ access: 'access-2' });
      }
      protectedCalls += 1;
      const token = new Headers(init?.headers).get('Authorization');
      return token === 'Bearer access-2'
        ? Response.json({ ok: true })
        : Response.json({ detail: 'expired' }, { status: 401 });
    };
    const session = new PosApiSession({
      baseUrl: 'https://tibatrace.example',
      storage,
      fetcher,
    });

    await session.restore();
    const response = await session.fetch('/api/pos/dispensing/episodes/queue/');

    expect(response.ok).toBe(true);
    expect(protectedCalls).toBe(2);
    expect(storage.value?.access).toBe('access-2');
  });

  it('clears an expired session when refresh is rejected', async () => {
    const storage = new MemoryStorage();
    storage.value = initial;
    const fetcher: typeof fetch = async (input) =>
      String(input).endsWith('/refresh/')
        ? Response.json({ detail: 'expired' }, { status: 401 })
        : Response.json({ detail: 'expired' }, { status: 401 });
    const session = new PosApiSession({
      baseUrl: 'https://tibatrace.example',
      storage,
      fetcher,
    });

    await session.restore();
    await expect(session.fetch('/api/pos/dispensing/episodes/queue/')).rejects.toEqual(
      expect.objectContaining<Partial<PosAuthenticationError>>({
        name: 'PosAuthenticationError',
        status: 401,
      }),
    );
    expect(storage.value).toBeNull();
  });

  it('rejects incomplete login responses', async () => {
    const session = new PosApiSession({
      baseUrl: 'https://tibatrace.example',
      storage: new MemoryStorage(),
      fetcher: async () => Response.json({ access: 'only-access' }),
    });

    await expect(session.login('cashier', 'secret')).rejects.toThrow(
      'sign-in response was incomplete',
    );
  });
});
