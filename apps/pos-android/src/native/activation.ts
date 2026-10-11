import type { PosDeviceCredentialDTO } from '@dawatrace/shared/dispensing/index.js';

import type { SecureKeyValueStore } from '../offline/secureStore';

export class SecureActivationStore {
  private readonly key: string;
  constructor(private readonly storage: SecureKeyValueStore, private readonly tenantId: string, private readonly deviceId: string) {
    this.key = `tibatrace.activation.v1.${tenantId}.${deviceId}`;
  }

  async load(): Promise<PosDeviceCredentialDTO | null> {
    const raw = await this.storage.getItem(this.key);
    if (!raw) return null;
    if (!(await this.storage.isAvailable())) throw new Error('Android secure activation storage is unavailable.');
    const value = JSON.parse(raw) as PosDeviceCredentialDTO;
    if (value.tenantId !== this.tenantId || value.deviceId !== this.deviceId || !value.signedToken) {
      throw new Error('Activation belongs to another tenant or installation.');
    }
    return value;
  }

  async save(value: PosDeviceCredentialDTO): Promise<void> {
    if (!(await this.storage.isAvailable())) throw new Error('Android secure activation storage is unavailable.');
    if (value.tenantId !== this.tenantId || value.deviceId !== this.deviceId || !value.signedToken || value.state !== 'ACTIVATED') {
      throw new Error('Invalid server-issued device activation.');
    }
    await this.storage.setItem(this.key, JSON.stringify(value));
  }
}
