import {
  PosApiSession,
  type PosSessionStorage,
  type PosSessionTokens,
} from '@dawatrace/shared/auth/index.js';
import { NativeModules } from 'react-native';

import type { SecureKeyValueStore } from '../offline/secureStore';

interface SecureStoreNativeModule {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
  isAvailable(): Promise<boolean>;
}

interface ConfigNativeModule {
  readonly apiBaseUrl: string;
  readonly versionName: string;
  readonly isDebug: boolean;
}

const secureModule = NativeModules['TibaTraceSecureStore'] as
  | SecureStoreNativeModule
  | undefined;
const configModule = NativeModules['TibaTraceConfig'] as ConfigNativeModule | undefined;
const SESSION_KEY = 'tibatrace.pos.session.v1';
const DEVICE_KEY = 'tibatrace.pos.device.v1';

export class AndroidSecureKeyValueStore implements SecureKeyValueStore {
  private get native(): SecureStoreNativeModule {
    if (!secureModule) throw new Error('Android secure storage is unavailable.');
    return secureModule;
  }

  getItem(key: string) {
    return this.native.getItem(key);
  }

  setItem(key: string, value: string) {
    return this.native.setItem(key, value);
  }

  removeItem(key: string) {
    return this.native.removeItem(key);
  }

  async isAvailable() {
    return secureModule ? secureModule.isAvailable() : false;
  }
}

class AndroidSessionStorage implements PosSessionStorage {
  constructor(private readonly storage: AndroidSecureKeyValueStore) {}

  async load(): Promise<PosSessionTokens | null> {
    const raw = await this.storage.getItem(SESSION_KEY);
    if (!raw) return null;
    try {
      const value = JSON.parse(raw) as Partial<PosSessionTokens>;
      if (
        !value.access ||
        !value.refresh ||
        !value.tenantId ||
        !value.userId
      ) {
        throw new Error('Session is incomplete.');
      }
      return {
        access: value.access,
        refresh: value.refresh,
        tenantId: value.tenantId,
        userId: value.userId,
      };
    } catch (cause) {
      throw new Error('The encrypted operator session could not be read.', { cause });
    }
  }

  save(tokens: PosSessionTokens) {
    return this.storage.setItem(SESSION_KEY, JSON.stringify(tokens));
  }

  clear() {
    return this.storage.removeItem(SESSION_KEY);
  }
}

export interface AndroidPosRuntime {
  readonly session: PosApiSession;
  readonly secureStore: AndroidSecureKeyValueStore;
  readonly apiBaseUrl: string;
  readonly version: string;
  deviceId(): Promise<string>;
  verify(username: string, password: string): Promise<boolean>;
}

export function createAndroidPosRuntime(): AndroidPosRuntime {
  const secureStore = new AndroidSecureKeyValueStore();
  const apiBaseUrl = validateApiBaseUrl(
    configModule?.apiBaseUrl ?? 'https://tibatrace.esenai.co.ke',
    configModule?.isDebug ?? false,
  );
  return {
    secureStore,
    apiBaseUrl,
    version: configModule?.versionName ?? '0.0.0',
    session: new PosApiSession({
      baseUrl: apiBaseUrl,
      storage: new AndroidSessionStorage(secureStore),
    }),
    async verify(username, password) {
      const current = this.session.current;
      if (!current) return false;
      const response = await fetch(`${apiBaseUrl}/api/identity/token/`, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      if (!response.ok) return false;
      const payload = (await response.json()) as { user_id?: unknown; tenant_id?: unknown };
      return payload.user_id === current.userId && payload.tenant_id === current.tenantId;
    },
    async deviceId() {
      const existing = await secureStore.getItem(DEVICE_KEY);
      if (existing) return existing;
      const created = createDeviceId();
      await secureStore.setItem(DEVICE_KEY, created);
      return created;
    },
  };
}

function validateApiBaseUrl(value: string, debug: boolean): string {
  const trimmed = value.replace(/\/+$/, '');
  if (
    !trimmed.startsWith('https://') &&
    !(debug && /^http:\/\/(10\.0\.2\.2|127\.0\.0\.1|localhost)(:\d+)?$/i.test(trimmed))
  ) {
    throw new Error('The Android POS API URL must use HTTPS.');
  }
  return trimmed;
}

function createDeviceId(): string {
  const random = Math.random().toString(16).slice(2);
  return `android-${Date.now().toString(16)}-${random}`;
}
