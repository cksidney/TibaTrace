import { randomUUID } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { app, BrowserWindow, ipcMain, net, session } from 'electron';

import { EncryptedSessionStore } from './sessionStore.js';
import type { StoredPosSession } from './sessionStore.js';
import { EncryptedOfflineStore } from './offlineStore.js';

const currentDirectory = dirname(fileURLToPath(import.meta.url));
const DEV_SERVER = process.env['VITE_DEV_SERVER_URL'];
const API_BASE_URL = normaliseApiBaseUrl(
  process.env['TIBATRACE_API_BASE_URL'] ?? 'https://tibatrace.esenai.co.ke',
);
const MAX_REQUEST_BYTES = 1024 * 1024;
const MAX_RESPONSE_BYTES = 10 * 1024 * 1024;
const ALLOWED_API_PREFIXES = ['/api/pos/', '/api/identity/me/', '/api/health/'];
const ALLOWED_RENDERER_HEADERS = new Set([
  'accept',
  'content-type',
  'idempotency-key',
  'x-request-id',
]);

interface ApiRequest {
  readonly path: string;
  readonly method?: string;
  readonly headers?: Record<string, string>;
  readonly body?: string;
}

interface ApiResponse {
  readonly status: number;
  readonly headers: Record<string, string>;
  readonly body: string;
}

interface LoginPayload {
  readonly username: string;
  readonly password: string;
}

interface TokenPayload {
  readonly access?: unknown;
  readonly refresh?: unknown;
  readonly tenant_id?: unknown;
  readonly user_id?: unknown;
}

let sessionStore: EncryptedSessionStore;
let deviceId = '';

function createWindow(): void {
  const window = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 720,
    icon: DEV_SERVER
      ? join(currentDirectory, '../../public/brand/tibatrace.ico')
      : join(currentDirectory, '../renderer/brand/tibatrace.ico'),
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(currentDirectory, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      spellcheck: false,
    },
  });

  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event, target) => {
    const packagedPage = pathToFileURL(
      join(currentDirectory, '../renderer/index.html'),
    ).toString();
    if (target !== packagedPage && (!DEV_SERVER || !target.startsWith(DEV_SERVER))) {
      event.preventDefault();
    }
  });
  window.once('ready-to-show', () => window.show());

  if (DEV_SERVER) {
    void window.loadURL(DEV_SERVER);
  } else {
    void window.loadFile(join(currentDirectory, '../renderer/index.html'));
  }
}

app.whenReady().then(async () => {
  sessionStore = new EncryptedSessionStore();
  deviceId = await readDeviceId();
  registerIpc();

  session.defaultSession.setPermissionRequestHandler(
    (_webContents, _permission, callback) => callback(false),
  );
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    const policy = DEV_SERVER
      ? "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-eval'; connect-src 'self' ws:; object-src 'none'; frame-src 'none'; base-uri 'none'"
      : "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'";
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [policy],
      },
    });
  });
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

function registerIpc(): void {
  ipcMain.handle('auth:restore', async () => sessionInfo(await sessionStore.load()));
  ipcMain.handle('auth:login', async (_event, payload: LoginPayload) => login(payload));
  ipcMain.handle('auth:verify', async (_event, payload: LoginPayload) => verifyOperator(payload));
  ipcMain.handle('auth:logout', async () => {
    await sessionStore.clear();
    return sessionInfo(null);
  });
  ipcMain.handle('api:request', async (_event, request: ApiRequest) => authorizedRequest(request));
  ipcMain.handle('offline:read', async () => {
    const stored = await requireSession();
    return new EncryptedOfflineStore(stored.tenantId, deviceId).read();
  });
  ipcMain.handle('offline:write', async (_event, actions: unknown) => {
    if (!Array.isArray(actions)) throw new Error('Invalid offline action journal.');
    const size = Buffer.byteLength(JSON.stringify(actions), 'utf8');
    if (size > 5 * 1024 * 1024) throw new Error('The offline action journal is too large.');
    const stored = await requireSession();
    await new EncryptedOfflineStore(stored.tenantId, deviceId).write(actions);
  });
}

async function requireSession(): Promise<StoredPosSession> {
  const stored = await sessionStore.load();
  if (!stored) throw new Error('Sign in is required.');
  return stored;
}

async function login(payload: LoginPayload) {
  const stored = await authenticate(payload);
  await sessionStore.save(stored);
  return sessionInfo(stored);
}

async function verifyOperator(payload: LoginPayload): Promise<boolean> {
  const current = await requireSession();
  const verified = await authenticate(payload);
  return verified.userId === current.userId && verified.tenantId === current.tenantId;
}

async function authenticate(payload: LoginPayload): Promise<StoredPosSession> {
  const username = String(payload?.username ?? '').trim();
  const password = String(payload?.password ?? '');
  if (!username || !password || username.length > 150 || password.length > 256) {
    throw new Error('Enter a valid username and password.');
  }

  const response = await net.fetch(`${API_BASE_URL}/api/identity/token/`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
    redirect: 'error',
  });
  const payloadBody = await readJson(response);
  if (!response.ok) throw new Error(apiError(payloadBody, 'Sign in was not accepted.'));

  const stored = readTokens(payloadBody);
  return stored;
}

async function authorizedRequest(request: ApiRequest): Promise<ApiResponse> {
  validateRequest(request);
  let stored = await sessionStore.load();
  if (!stored) throw new Error('Sign in is required.');

  let response = await executeApiRequest(request, stored);
  if (response.status !== 401) return response;

  stored = await refresh(stored);
  if (!stored) {
    await sessionStore.clear();
    throw new Error('The session has expired. Sign in again.');
  }
  response = await executeApiRequest(request, stored);
  return response;
}

async function executeApiRequest(
  request: ApiRequest,
  stored: StoredPosSession,
): Promise<ApiResponse> {
  const headers = new Headers();
  for (const [name, value] of Object.entries(request.headers ?? {})) {
    if (ALLOWED_RENDERER_HEADERS.has(name.toLowerCase())) headers.set(name, value);
  }
  headers.set('Authorization', `Bearer ${stored.access}`);
  headers.set('X-Tenant-ID', stored.tenantId);
  headers.set('Accept', headers.get('Accept') ?? 'application/json');

  const response = await net.fetch(`${API_BASE_URL}${request.path}`, {
    method: (request.method ?? 'GET').toUpperCase(),
    headers,
    ...(request.body === undefined ? {} : { body: request.body }),
    redirect: 'error',
  });
  const body = await response.text();
  if (Buffer.byteLength(body, 'utf8') > MAX_RESPONSE_BYTES) {
    throw new Error('The server response exceeded the POS safety limit.');
  }
  return {
    status: response.status,
    headers: {
      'content-type': response.headers.get('content-type') ?? 'application/json',
      'x-request-id': response.headers.get('x-request-id') ?? '',
    },
    body,
  };
}

async function refresh(stored: StoredPosSession): Promise<StoredPosSession | null> {
  const response = await net.fetch(`${API_BASE_URL}/api/identity/token/refresh/`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh: stored.refresh }),
    redirect: 'error',
  });
  if (!response.ok) return null;
  const payload = (await readJson(response)) as { access?: unknown; refresh?: unknown };
  if (typeof payload.access !== 'string' || !payload.access) return null;
  const next: StoredPosSession = {
    ...stored,
    access: payload.access,
    refresh:
      typeof payload.refresh === 'string' && payload.refresh
        ? payload.refresh
        : stored.refresh,
  };
  await sessionStore.save(next);
  return next;
}

function validateRequest(request: ApiRequest): void {
  if (!request || typeof request.path !== 'string') throw new Error('Invalid API request.');
  if (
    !ALLOWED_API_PREFIXES.some((prefix) => request.path.startsWith(prefix)) ||
    request.path.startsWith('/api/identity/token') ||
    request.path.includes('://') ||
    request.path.includes('\\') ||
    request.path.includes('..') ||
    /%2e/i.test(request.path)
  ) {
    throw new Error('The requested API path is not allowed.');
  }
  const method = (request.method ?? 'GET').toUpperCase();
  if (!['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    throw new Error('The requested API method is not allowed.');
  }
  if (request.body && Buffer.byteLength(request.body, 'utf8') > MAX_REQUEST_BYTES) {
    throw new Error('The API request exceeded the POS safety limit.');
  }
}

function readTokens(payload: unknown): StoredPosSession {
  if (!payload || typeof payload !== 'object') {
    throw new Error('The sign-in response could not be read.');
  }
  const value = payload as TokenPayload;
  if (
    typeof value.access !== 'string' ||
    !value.access ||
    typeof value.refresh !== 'string' ||
    !value.refresh ||
    typeof value.tenant_id !== 'string' ||
    !value.tenant_id ||
    typeof value.user_id !== 'string' ||
    !value.user_id
  ) {
    throw new Error('The sign-in response was incomplete.');
  }
  return {
    access: value.access,
    refresh: value.refresh,
    tenantId: value.tenant_id,
    userId: value.user_id,
  };
}

function sessionInfo(stored: StoredPosSession | null) {
  return {
    authenticated: stored !== null,
    tenantId: stored?.tenantId ?? '',
    userId: stored?.userId ?? '',
    deviceId,
    apiBaseUrl: API_BASE_URL,
  };
}

async function readDeviceId(): Promise<string> {
  const directory = join(app.getPath('userData'), 'device');
  const file = join(directory, 'id');
  if (existsSync(file)) {
    const existing = (await readFile(file, 'utf8')).trim();
    if (/^[0-9a-f-]{36}$/i.test(existing)) return existing;
  }
  const created = randomUUID();
  await mkdir(directory, { recursive: true });
  await writeFile(file, created, { encoding: 'utf8', mode: 0o600 });
  return created;
}

function normaliseApiBaseUrl(value: string): string {
  const url = new URL(value);
  const isLocal = ['localhost', '127.0.0.1'].includes(url.hostname);
  if (url.protocol !== 'https:' && !(isLocal && url.protocol === 'http:')) {
    throw new Error('TIBATRACE_API_BASE_URL must use HTTPS.');
  }
  return url.origin;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function apiError(payload: unknown, fallback: string): string {
  if (payload && typeof payload === 'object') {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail) return detail;
  }
  return fallback;
}
