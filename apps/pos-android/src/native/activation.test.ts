import type { PosDeviceCredentialDTO } from '@dawatrace/shared/dispensing/index.js';
import { describe, expect, it } from 'vitest';

import { SecureActivationStore } from './activation';
import type { SecureKeyValueStore } from '../offline/secureStore';

function storage(available = true) {
  const values = new Map<string, string>();
  const store: SecureKeyValueStore = {
    getItem: async (key) => values.get(key) ?? null,
    setItem: async (key, value) => { values.set(key, value); },
    removeItem: async (key) => { values.delete(key); },
    isAvailable: async () => available,
  };
  return { values, store };
}
const credential: PosDeviceCredentialDTO = {
  activationId: 'request', tenantId: 'tenant', branchId: 'branch', deviceId: 'device',
  deviceFingerprint: 'installation-fingerprint', state: 'ACTIVATED', appVersion: 'test', minimumRequiredBuild: '0',
  issuedAt: '2026-10-11T00:00:00Z', expiresAt: '2027-10-11T00:00:00Z', signedToken: 'test-only-signed-credential', isRevoked: false,
};

describe('Android activation storage', () => {
  it('round-trips only within the same tenant and device', async () => {
    const { store } = storage();
    const activation = new SecureActivationStore(store, 'tenant', 'device');
    await activation.save(credential);
    expect(await activation.load()).toEqual(credential);
    expect(await new SecureActivationStore(store, 'other', 'device').load()).toBeNull();
  });
  it('refuses copied credentials and unavailable secure storage', async () => {
    const { store } = storage();
    await expect(new SecureActivationStore(store, 'other', 'device').save(credential)).rejects.toThrow();
    const unavailable = storage(false);
    await expect(new SecureActivationStore(unavailable.store, 'tenant', 'device').save(credential)).rejects.toThrow();
    expect(unavailable.values.size).toBe(0);
  });
  it('fails closed on corrupted storage instead of inventing activation', async () => {
    const { values, store } = storage();
    values.set('tibatrace.activation.v1.tenant.device', 'not-json');
    await expect(new SecureActivationStore(store, 'tenant', 'device').load()).rejects.toThrow();
  });
});
