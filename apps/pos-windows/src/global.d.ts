interface TibaTraceSessionInfo {
  readonly authenticated: boolean;
  readonly tenantId: string;
  readonly userId: string;
  /** Who is signed in, for display. Absent on an Electron build that predates it. */
  readonly username?: string;
  readonly deviceId: string;
  readonly apiBaseUrl: string;
}

interface TibaTraceApiResponse {
  readonly status: number;
  readonly headers: Record<string, string>;
  readonly body: string;
}

interface Window {
  readonly tibatrace?: {
    readonly platform: 'windows';
    readonly version: string;
    readonly auth: {
      restore(): Promise<TibaTraceSessionInfo>;
      login(username: string, password: string): Promise<TibaTraceSessionInfo>;
      logout(): Promise<TibaTraceSessionInfo>;
    };
    readonly api: {
      request(request: {
        readonly path: string;
        readonly method?: string;
        readonly headers?: Record<string, string>;
        readonly body?: string;
      }): Promise<TibaTraceApiResponse>;
    };
    readonly offline: {
      read(): Promise<unknown[]>;
      write(actions: readonly unknown[]): Promise<void>;
    };
  };
}
