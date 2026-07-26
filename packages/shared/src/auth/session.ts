export interface PosSessionTokens {
  readonly access: string;
  readonly refresh: string;
  readonly tenantId: string;
  readonly userId: string;
}

export interface PosSessionStorage {
  load(): Promise<PosSessionTokens | null>;
  save(tokens: PosSessionTokens): Promise<void>;
  clear(): Promise<void>;
}

export interface PosApiSessionOptions {
  readonly baseUrl: string;
  readonly storage: PosSessionStorage;
  readonly fetcher?: typeof fetch;
}

interface LoginResponse {
  readonly access?: unknown;
  readonly refresh?: unknown;
  readonly tenant_id?: unknown;
  readonly user_id?: unknown;
}

interface RefreshResponse {
  readonly access?: unknown;
  readonly refresh?: unknown;
}

export class PosAuthenticationError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'PosAuthenticationError';
    this.status = status;
  }
}

export class PosApiSession {
  private readonly baseUrl: string;
  private readonly storage: PosSessionStorage;
  private readonly fetcher: typeof fetch;
  private tokens: PosSessionTokens | null = null;
  private refreshPromise: Promise<boolean> | null = null;

  constructor(options: PosApiSessionOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.storage = options.storage;
    this.fetcher = options.fetcher ?? fetch;
  }

  get current(): PosSessionTokens | null {
    return this.tokens;
  }

  async restore(): Promise<PosSessionTokens | null> {
    this.tokens = await this.storage.load();
    return this.tokens;
  }

  async login(username: string, password: string): Promise<PosSessionTokens> {
    const response = await this.fetcher(`${this.baseUrl}/api/identity/token/`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ username, password }),
    });
    const payload = await readJson(response);
    if (!response.ok) {
      throw new PosAuthenticationError(errorMessage(payload), response.status);
    }

    const tokens = readLoginResponse(payload);
    this.tokens = tokens;
    await this.storage.save(tokens);
    return tokens;
  }

  async logout(): Promise<void> {
    this.tokens = null;
    await this.storage.clear();
  }

  async fetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
    if (!this.tokens) {
      throw new PosAuthenticationError('Sign in is required.', 401);
    }

    const first = await this.authorizedFetch(input, init, this.tokens);
    if (first.status !== 401) return first;

    if (!(await this.refresh())) {
      await this.logout();
      throw new PosAuthenticationError('The session has expired. Sign in again.', 401);
    }

    return this.authorizedFetch(input, init, this.tokens as PosSessionTokens);
  }

  private authorizedFetch(
    input: RequestInfo | URL,
    init: RequestInit,
    tokens: PosSessionTokens,
  ): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set('Authorization', `Bearer ${tokens.access}`);
    headers.set('X-Tenant-ID', tokens.tenantId);
    headers.set('Accept', headers.get('Accept') ?? 'application/json');
    return this.fetcher(this.resolveUrl(input), { ...init, headers });
  }

  private resolveUrl(input: RequestInfo | URL): string | URL {
    if (input instanceof URL) return input;
    if (input instanceof Request) return this.resolveUrl(input.url);
    if (/^https?:\/\//i.test(input)) return input;
    return `${this.baseUrl}${input.startsWith('/') ? input : `/${input}`}`;
  }

  private async refresh(): Promise<boolean> {
    if (!this.tokens?.refresh) return false;
    if (this.refreshPromise) return this.refreshPromise;

    this.refreshPromise = this.performRefresh();
    try {
      return await this.refreshPromise;
    } finally {
      this.refreshPromise = null;
    }
  }

  private async performRefresh(): Promise<boolean> {
    const existing = this.tokens;
    if (!existing) return false;

    const response = await this.fetcher(`${this.baseUrl}/api/identity/token/refresh/`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ refresh: existing.refresh }),
    });
    if (!response.ok) return false;

    const payload = (await readJson(response)) as RefreshResponse;
    if (typeof payload.access !== 'string' || !payload.access) return false;

    const tokens: PosSessionTokens = {
      ...existing,
      access: payload.access,
      refresh:
        typeof payload.refresh === 'string' && payload.refresh
          ? payload.refresh
          : existing.refresh,
    };
    this.tokens = tokens;
    await this.storage.save(tokens);
    return true;
  }
}

function readLoginResponse(payload: unknown): PosSessionTokens {
  if (!payload || typeof payload !== 'object') {
    throw new PosAuthenticationError('The sign-in response could not be read.', 502);
  }
  const response = payload as LoginResponse;
  if (
    typeof response.access !== 'string' ||
    !response.access ||
    typeof response.refresh !== 'string' ||
    !response.refresh ||
    typeof response.tenant_id !== 'string' ||
    !response.tenant_id ||
    typeof response.user_id !== 'string' ||
    !response.user_id
  ) {
    throw new PosAuthenticationError('The sign-in response was incomplete.', 502);
  }
  return {
    access: response.access,
    refresh: response.refresh,
    tenantId: response.tenant_id,
    userId: response.user_id,
  };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function errorMessage(payload: unknown): string {
  if (payload && typeof payload === 'object') {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail) return detail;
  }
  return 'Sign in was not accepted.';
}
