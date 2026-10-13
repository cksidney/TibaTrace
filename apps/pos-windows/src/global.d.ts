interface TibaTraceSessionInfo {
  readonly authenticated: boolean;
  readonly tenantId: string;
  readonly userId: string;
  /** Who is signed in, for display. Absent on an Electron build that predates it. */
  readonly username?: string;
  readonly deviceId: string;
  readonly apiBaseUrl: string;
  readonly deviceFingerprint?: string;
  readonly appVersion?: string;
  readonly activationValid?: boolean;
  readonly activationBranchId?: string;
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
      verify(username: string, password: string): Promise<boolean>;
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
    readonly print: {
      printers(): Promise<readonly { name: string; displayName: string }[]>;
      document(jobId: string, printer: string): Promise<{ accepted: boolean; message: string }>;
    };
  };
}
