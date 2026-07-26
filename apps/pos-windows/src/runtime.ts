import {
  PosApiSession,
  type PosSessionStorage,
  type PosSessionTokens,
} from '@dawatrace/shared/auth/index.js';
import type {
  OfflineAction,
  OfflineStore,
} from '@dawatrace/shared/dispensing/index.js';

export interface PosRuntime {
  restore(): Promise<TibaTraceSessionInfo>;
  login(username: string, password: string): Promise<TibaTraceSessionInfo>;
  logout(): Promise<void>;
  readonly fetch: typeof fetch;
  readonly offline: OfflineStore;
}

class MemorySessionStorage implements PosSessionStorage {
  private value: PosSessionTokens | null = null;

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

export function createPosRuntime(): PosRuntime {
  if (window.tibatrace) {
    const electronFetch: typeof fetch = async (input, init) => {
      const request = new Request(input, init);
      const url = new URL(request.url);
      const headers: Record<string, string> = {};
      request.headers.forEach((value, key) => {
        headers[key] = value;
      });
      const body =
        request.method === 'GET' || request.method === 'HEAD'
          ? undefined
          : await request.text();
      const response = await window.tibatrace!.api.request({
        path: `${url.pathname}${url.search}`,
        method: request.method,
        ...(Object.keys(headers).length ? { headers } : {}),
        ...(body === undefined ? {} : { body }),
      });
      return new Response(response.body, {
        status: response.status,
        headers: response.headers,
      });
    };
    return {
      restore: () => window.tibatrace!.auth.restore(),
      login: (username, password) => window.tibatrace!.auth.login(username, password),
      logout: async () => {
        await window.tibatrace!.auth.logout();
      },
      fetch: electronFetch,
      offline: {
        read: async () =>
          (await window.tibatrace!.offline.read()) as readonly OfflineAction[],
        write: (actions) => window.tibatrace!.offline.write(actions),
        clear: async () => {
          await window.tibatrace!.offline.write([]);
        },
      },
    };
  }

  const session = new PosApiSession({
    baseUrl: '',
    storage: new MemorySessionStorage(),
  });
  let offlineActions: readonly OfflineAction[] = [];
  const unauthenticatedInfo = (): TibaTraceSessionInfo => ({
    authenticated: session.current !== null,
    tenantId: session.current?.tenantId ?? '',
    userId: session.current?.userId ?? '',
    deviceId: 'POS-WINDOWS-DEVELOPMENT',
    apiBaseUrl: window.location.origin,
  });
  return {
    restore: async () => {
      await session.restore();
      return unauthenticatedInfo();
    },
    login: async (username, password) => {
      await session.login(username, password);
      return unauthenticatedInfo();
    },
    logout: () => session.logout(),
    fetch: session.fetch.bind(session) as typeof fetch,
    offline: {
      read: async () => offlineActions,
      write: async (actions) => {
        offlineActions = actions;
      },
      clear: async () => {
        offlineActions = [];
      },
    },
  };
}
