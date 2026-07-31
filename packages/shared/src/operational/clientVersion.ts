/**
 * POS ↔ HQ client version alignment.
 *
 * Tills call this on Sync Centre open and at most once per calendar day so
 * operational upgrades published in HQ (screening, dispensing, cash) surface
 * before the operator keeps working on a stale binary.
 */
import { resolveFetcher } from '../auth/fetcher.js';

export interface PosClientVersionStatus {
  readonly platform: string;
  readonly client_version: string;
  readonly client_build: number;
  readonly latest_version: string;
  readonly latest_build: number;
  readonly update_available: boolean;
  readonly update_required: boolean;
  readonly operations_impact: string;
  readonly release_notes: string;
  readonly checked_at: string;
  readonly next_check_after_hours: number;
}

export type PosClientPlatform = 'WINDOWS' | 'ANDROID' | 'WEB';

export interface CheckPosClientVersionInput {
  readonly platform: PosClientPlatform;
  readonly version: string;
  readonly buildNumber?: number;
  readonly fetcher?: typeof fetch;
  readonly baseUrl?: string;
}

const STORAGE_KEY = 'tibatrace.pos.client-version.v1';
const DAY_MS = 24 * 60 * 60 * 1000;

interface CachedCheck {
  readonly checkedAt: number;
  readonly status: PosClientVersionStatus;
}

function readCache(): CachedCheck | null {
  try {
    if (typeof localStorage === 'undefined') return null;
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as CachedCheck;
  } catch {
    return null;
  }
}

function writeCache(status: PosClientVersionStatus): void {
  try {
    if (typeof localStorage === 'undefined') return;
    const payload: CachedCheck = { checkedAt: Date.now(), status };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Private mode / RN without polyfill — daily check still runs in-memory.
  }
}

/** True when a fresh HQ check is due (or never ran). */
export function isPosClientVersionCheckDue(now = Date.now()): boolean {
  const cached = readCache();
  if (!cached) return true;
  const hours = cached.status.next_check_after_hours || 24;
  return now - cached.checkedAt >= hours * 60 * 60 * 1000 || now - cached.checkedAt >= DAY_MS;
}

export function getCachedPosClientVersion(): PosClientVersionStatus | null {
  return readCache()?.status ?? null;
}

export async function checkPosClientVersion(
  input: CheckPosClientVersionInput,
  options: { readonly force?: boolean } = {},
): Promise<PosClientVersionStatus> {
  if (!options.force && !isPosClientVersionCheckDue()) {
    const cached = getCachedPosClientVersion();
    if (cached) return cached;
  }

  const fetcher = resolveFetcher(input.fetcher);
  const base = (input.baseUrl ?? '').replace(/\/$/, '');
  const params = new URLSearchParams({
    platform: input.platform,
    version: input.version,
    build_number: String(input.buildNumber ?? 0),
  });
  const response = await fetcher(`${base}/api/pos/client-version/?${params.toString()}`, {
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      'X-POS-Client-Platform': input.platform,
      'X-POS-Client-Version': input.version,
      'X-POS-Client-Build': String(input.buildNumber ?? 0),
    },
  });
  if (!response.ok) {
    throw new Error(`Client version check failed (${response.status}).`);
  }
  const status = (await response.json()) as PosClientVersionStatus;
  writeCache(status);
  return status;
}

/** Headers every mutating POS call should carry after a version check. */
export function posClientVersionHeaders(input: {
  readonly platform: PosClientPlatform;
  readonly version: string;
  readonly buildNumber?: number;
}): Record<string, string> {
  return {
    'X-POS-Client-Platform': input.platform,
    'X-POS-Client-Version': input.version,
    'X-POS-Client-Build': String(input.buildNumber ?? 0),
  };
}
