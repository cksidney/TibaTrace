import type { OfflineAction } from '@dawatrace/shared/dispensing/index.js';
import { describe, expect, it } from 'vitest';

import type { SecureKeyValueStore } from './secureStore.js';
import {
  OfflineStoreUnavailable,
  OfflineStoreUnreadable,
  SecureOfflineStore,
} from './secureStore.js';

function keystore(options: { available?: boolean; initial?: Record<string, string> } = {}) {
  const data = new Map(Object.entries(options.initial ?? {}));
  const impl: SecureKeyValueStore & { data: Map<string, string> } = {
    data,
    async getItem(key) {
      return data.get(key) ?? null;
    },
    async setItem(key, value) {
      data.set(key, value);
    },
    async removeItem(key) {
      data.delete(key);
    },
    async isAvailable() {
      return options.available ?? true;
    },
  };
  return impl;
}

function store(ks: SecureKeyValueStore, tenantId = 'tenant-1', deviceId = 'TILL-1') {
  return new SecureOfflineStore({ keystore: ks, tenantId, deviceId });
}

function action(overrides: Partial<OfflineAction> = {}): OfflineAction {
  return {
    id: 'a-1',
    type: 'SUPPLY',
    episodeId: 'ep-1',
    idempotencyKey: 'supply:ep-1:1',
    payload: {},
    state: 'PENDING',
    queuedAt: '2026-01-01T09:00:00Z',
    attempts: 0,
    ...overrides,
  };
}

describe('encryption requirement', () => {
  it('refuses to write when hardware-backed storage is unavailable', async () => {
    // A "temporarily unencrypted" fallback is how patient references and
    // pending payments end up in plaintext on a shared device.
    const target = store(keystore({ available: false }));
    await expect(target.write([action()])).rejects.toBeInstanceOf(OfflineStoreUnavailable);
  });

  it('writes when encryption is available', async () => {
    const ks = keystore();
    await store(ks).write([action()]);
    expect(ks.data.size).toBe(1);
  });

  it('does not fall back to a plaintext key', async () => {
    const ks = keystore({ available: false });
    await expect(store(ks).write([action()])).rejects.toThrow();
    expect(ks.data.size).toBe(0);
  });
});

describe('reading', () => {
  it('returns an empty queue when nothing has been stored', async () => {
    expect(await store(keystore()).read()).toEqual([]);
  });

  it('round-trips queued actions', async () => {
    const ks = keystore();
    const target = store(ks);
    await target.write([action({ id: 'a' }), action({ id: 'b' })]);
    expect((await target.read()).map((a) => a.id)).toEqual(['a', 'b']);
  });

  it('raises rather than reporting an empty queue when the value is corrupt', async () => {
    // Silently returning [] would drop supplies that physically happened.
    const ks = keystore({ initial: { 'dawatrace.offline.tenant-1.TILL-1': 'not-json' } });
    await expect(store(ks).read()).rejects.toBeInstanceOf(OfflineStoreUnreadable);
  });

  it('refuses a queue written by an unsupported version', async () => {
    const ks = keystore({
      initial: {
        'dawatrace.offline.tenant-1.TILL-1': JSON.stringify({
          version: 99,
          tenantId: 'tenant-1',
          deviceId: 'TILL-1',
          actions: [],
        }),
      },
    });
    await expect(store(ks).read()).rejects.toBeInstanceOf(OfflineStoreUnreadable);
  });
});

describe('tenant and device scoping', () => {
  it('does not read another tenant queue', async () => {
    const ks = keystore();
    await store(ks, 'tenant-1').write([action()]);
    // A different tenant sees nothing, because the key is namespaced.
    expect(await store(ks, 'tenant-2').read()).toEqual([]);
  });

  it('rejects a value restored from a backup of another device', async () => {
    const ks = keystore({
      initial: {
        'dawatrace.offline.tenant-1.TILL-1': JSON.stringify({
          version: 1,
          tenantId: 'tenant-1',
          deviceId: 'SOME-OTHER-TILL',
          writtenAt: '2026-01-01T09:00:00Z',
          actions: [action()],
        }),
      },
    });
    await expect(store(ks).read()).rejects.toBeInstanceOf(OfflineStoreUnreadable);
  });

  it('clears only its own namespace', async () => {
    const ks = keystore();
    await store(ks, 'tenant-1').write([action()]);
    await store(ks, 'tenant-2').write([action()]);

    await store(ks, 'tenant-1').clear();
    expect(await store(ks, 'tenant-1').read()).toEqual([]);
    expect(await store(ks, 'tenant-2').read()).toHaveLength(1);
  });
});
