import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

import { app, safeStorage } from 'electron';

export interface DeviceActivation {
  readonly tenantId: string;
  readonly deviceId: string;
  readonly deviceFingerprint: string;
  readonly branchId: string;
  readonly signedToken: string;
  readonly expiresAt: string;
  readonly state: string;
}

/** Device credentials never use renderer storage or a bundled encryption key. */
export class EncryptedActivationStore {
  private readonly directory = join(app.getPath('userData'), 'activation');
  private readonly file: string;

  constructor(private readonly tenantId: string, private readonly deviceId: string) {
    const key = createHash('sha256').update(`${tenantId}:${deviceId}`).digest('hex');
    this.file = join(this.directory, `${key}.enc`);
  }

  async load(): Promise<DeviceActivation | null> {
    if (!existsSync(this.file)) return null;
    if (!safeStorage.isEncryptionAvailable()) throw new Error('Secure activation storage is unavailable.');
    const value = JSON.parse(safeStorage.decryptString(await readFile(this.file))) as DeviceActivation;
    if (value.tenantId !== this.tenantId || value.deviceId !== this.deviceId || !value.signedToken) {
      throw new Error('Stored activation does not belong to this tenant and device.');
    }
    return value;
  }

  async save(value: DeviceActivation): Promise<void> {
    if (value.tenantId !== this.tenantId || value.deviceId !== this.deviceId || !value.signedToken || value.state !== 'ACTIVATED') {
      throw new Error('Invalid server-issued device activation.');
    }
    if (!safeStorage.isEncryptionAvailable()) throw new Error('Secure activation storage is unavailable.');
    await mkdir(this.directory, { recursive: true });
    const temp = `${this.file}.tmp`;
    await writeFile(temp, safeStorage.encryptString(JSON.stringify(value)), { mode: 0o600 });
    await rename(temp, this.file);
  }
}
