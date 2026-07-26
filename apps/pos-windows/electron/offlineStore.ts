import { existsSync } from 'node:fs';
import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

import { app, safeStorage } from 'electron';

/**
 * Encrypted, device-scoped offline store for the Windows till.
 *
 * Holds queued clinical and financial actions that have not yet been confirmed
 * by the server, so they survive a crash or power cut. That makes the file
 * genuinely sensitive: it contains patient references and pending money
 * movements.
 *
 * Encryption uses Electron's safeStorage, which is backed by the OS keychain
 * (DPAPI on Windows). The key never lives in the bundle or on disk beside the
 * data -- shipping a key alongside what it protects is the same as shipping
 * plaintext.
 */

const FILE_VERSION = 1;

interface StoredEnvelope {
  readonly version: number;
  readonly tenantId: string;
  readonly deviceId: string;
  readonly writtenAt: string;
  readonly actions: unknown[];
}

export class EncryptedOfflineStore {
  private readonly tenantId: string;
  private readonly deviceId: string;
  private readonly directory: string;

  constructor(tenantId: string, deviceId: string) {
    this.tenantId = tenantId;
    this.deviceId = deviceId;
    // Scoped by tenant and device: a queue must never be readable across a
    // tenant switch, and two terminals must not share pending actions.
    this.directory = join(app.getPath('userData'), 'offline', tenantId, deviceId);
  }

  private get file(): string {
    return join(this.directory, 'queue.enc');
  }

  private get temp(): string {
    return join(this.directory, 'queue.enc.tmp');
  }

  /** Whether the OS can actually encrypt. Refuses to degrade silently. */
  static encryptionAvailable(): boolean {
    return safeStorage.isEncryptionAvailable();
  }

  async read(): Promise<unknown[]> {
    if (!existsSync(this.file)) return [];

    let plaintext: string;
    try {
      const ciphertext = await readFile(this.file);
      plaintext = safeStorage.decryptString(ciphertext);
    } catch {
      // A queue we cannot decrypt is not a queue we may act on. Returning an
      // empty list here would silently drop pending supplies, so the caller is
      // told loudly instead.
      throw new OfflineStoreUnreadable(
        'The offline queue could not be decrypted on this device. It must be reconciled with the server before dispensing continues.',
      );
    }

    const envelope = JSON.parse(plaintext) as StoredEnvelope;
    if (envelope.version !== FILE_VERSION) {
      throw new OfflineStoreUnreadable(
        `Offline queue was written by an unsupported version (${envelope.version}).`,
      );
    }
    // Belt and braces: the path is already scoped, but a file moved between
    // installations must not be adopted by the wrong tenant or device.
    if (envelope.tenantId !== this.tenantId || envelope.deviceId !== this.deviceId) {
      throw new OfflineStoreUnreadable(
        'Offline queue belongs to a different tenant or device and will not be used.',
      );
    }
    return envelope.actions;
  }

  async write(actions: readonly unknown[]): Promise<void> {
    if (!EncryptedOfflineStore.encryptionAvailable()) {
      // Writing pending payments and patient references in plaintext is not an
      // acceptable fallback.
      throw new OfflineStoreUnavailable(
        'Encrypted storage is unavailable on this device, so offline dispensing cannot be used.',
      );
    }

    await mkdir(this.directory, { recursive: true });
    const envelope: StoredEnvelope = {
      version: FILE_VERSION,
      tenantId: this.tenantId,
      deviceId: this.deviceId,
      writtenAt: new Date().toISOString(),
      actions: [...actions],
    };

    const ciphertext = safeStorage.encryptString(JSON.stringify(envelope));
    // Write-then-rename: a power cut mid-write must leave the previous queue
    // intact rather than a truncated file that reads as an empty queue.
    await writeFile(this.temp, ciphertext);
    await rename(this.temp, this.file);
  }

  /** Clear on logout or tenant switch. */
  async clear(): Promise<void> {
    for (const path of [this.file, this.temp]) {
      if (existsSync(path)) await unlink(path);
    }
  }
}

export class OfflineStoreUnreadable extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'OfflineStoreUnreadable';
  }
}

export class OfflineStoreUnavailable extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'OfflineStoreUnavailable';
  }
}
