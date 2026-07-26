import type { OfflineAction, OfflineStore } from '@dawatrace/shared/dispensing/index.js';

/**
 * Encrypted, device-scoped offline store for the Android till.
 *
 * Unlike Electron, React Native has no built-in equivalent of safeStorage, and
 * the right native module depends on how the app is packaged (Expo SecureStore,
 * react-native-keychain, or an EncryptedSharedPreferences bridge). Rather than
 * bake one in, this takes the keystore as a dependency and refuses to run
 * without it.
 *
 * That refusal is the point: an offline queue holds patient references and
 * pending money movements, and a "temporarily unencrypted" fallback is how that
 * data ends up in a plaintext file on a shared device.
 */

/**
 * The native capability this store requires.
 *
 * Implementations must be backed by the Android keystore. AsyncStorage on its
 * own does not satisfy this -- it is unencrypted app storage.
 */
export interface SecureKeyValueStore {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
  /** Whether hardware-backed encryption is actually available right now. */
  isAvailable(): Promise<boolean>;
}

const ENVELOPE_VERSION = 1;

interface StoredEnvelope {
  readonly version: number;
  readonly tenantId: string;
  readonly deviceId: string;
  readonly writtenAt: string;
  readonly actions: readonly OfflineAction[];
}

export class SecureOfflineStore implements OfflineStore {
  private readonly keystore: SecureKeyValueStore;
  private readonly tenantId: string;
  private readonly deviceId: string;

  constructor(options: {
    keystore: SecureKeyValueStore;
    tenantId: string;
    deviceId: string;
  }) {
    this.keystore = options.keystore;
    this.tenantId = options.tenantId;
    this.deviceId = options.deviceId;
  }

  /** Namespaced so a tenant switch cannot read the previous tenant's queue. */
  private get key(): string {
    return `dawatrace.offline.${this.tenantId}.${this.deviceId}`;
  }

  async read(): Promise<readonly OfflineAction[]> {
    const raw = await this.keystore.getItem(this.key);
    if (!raw) return [];

    let envelope: StoredEnvelope;
    try {
      envelope = JSON.parse(raw) as StoredEnvelope;
    } catch {
      // A queue we cannot parse is not a queue we may act on. Returning an
      // empty list would silently drop supplies that physically happened.
      throw new OfflineStoreUnreadable(
        'The offline queue on this device could not be read. It must be reconciled with the server before dispensing continues.',
      );
    }

    if (envelope.version !== ENVELOPE_VERSION) {
      throw new OfflineStoreUnreadable(
        `Offline queue was written by an unsupported version (${envelope.version}).`,
      );
    }
    // The key is already namespaced; this catches a value restored from a
    // backup or copied between installations.
    if (envelope.tenantId !== this.tenantId || envelope.deviceId !== this.deviceId) {
      throw new OfflineStoreUnreadable(
        'Offline queue belongs to a different tenant or device and will not be used.',
      );
    }
    if (!Array.isArray(envelope.actions)) {
      throw new OfflineStoreUnreadable(
        'The offline queue contained no valid action list and will not be used.',
      );
    }
    return envelope.actions;
  }

  async write(actions: readonly OfflineAction[]): Promise<void> {
    if (!(await this.keystore.isAvailable())) {
      // No silent plaintext fallback. Offline dispensing simply stops.
      throw new OfflineStoreUnavailable(
        'Hardware-backed encrypted storage is unavailable on this device, so offline dispensing cannot be used.',
      );
    }

    const envelope: StoredEnvelope = {
      version: ENVELOPE_VERSION,
      tenantId: this.tenantId,
      deviceId: this.deviceId,
      writtenAt: new Date().toISOString(),
      actions,
    };
    await this.keystore.setItem(this.key, JSON.stringify(envelope));
  }

  /** Clear only after every queued action is terminal and retained elsewhere. */
  async clear(): Promise<void> {
    await this.keystore.removeItem(this.key);
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
