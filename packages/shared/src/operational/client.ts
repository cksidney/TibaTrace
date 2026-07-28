import { resolveFetcher } from '../auth/fetcher.js';

import type {
  BusinessDayDTO,
  DeviceHealthDTO,
  OperatorShiftDTO,
  PosRegisterDTO,
  RegisterSessionDTO,
} from './types.js';

export interface PosOperationsClientOptions {
  readonly fetcher?: typeof fetch;
}

export class PosOperationsClient {
  private readonly fetcher: typeof fetch;

  constructor(
    private readonly baseUrl = '/api/pos/shift',
    options: PosOperationsClientOptions = {},
  ) {
    this.fetcher = resolveFetcher(options.fetcher);
  }

  async getRegisters(): Promise<readonly PosRegisterDTO[]> {
    return this.collection<PosRegisterDTO>('/registers/');
  }

  async getBusinessDays(): Promise<readonly BusinessDayDTO[]> {
    return this.collection<BusinessDayDTO>('/business-days/');
  }

  async getOpenSessions(): Promise<readonly RegisterSessionDTO[]> {
    return this.collection<RegisterSessionDTO>('/sessions/open/');
  }

  async getDevices(): Promise<readonly DeviceHealthDTO[]> {
    return this.collection<DeviceHealthDTO>('/devices/');
  }

  async getOperatorShifts(): Promise<readonly OperatorShiftDTO[]> {
    return this.collection<OperatorShiftDTO>('/shifts/');
  }

  async getRuntime(deviceId: string): Promise<import('./types.js').PosOperationalRuntimeDTO> {
    const response = await this.fetcher(
      `${this.baseUrl}/registers/runtime/?device_id=${encodeURIComponent(deviceId)}`,
      {
        credentials: 'include',
        headers: { Accept: 'application/json' },
      },
    );
    if (!response.ok) {
      throw new Error(`Operational status request failed with ${response.status}.`);
    }
    return (await response.json()) as import('./types.js').PosOperationalRuntimeDTO;
  }

  private async collection<T>(path: string): Promise<readonly T[]> {
    const response = await this.fetcher(`${this.baseUrl}${path}`, {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) {
      throw new Error(`Operational status request failed with ${response.status}.`);
    }
    return readCollection<T>(await response.json());
  }
}

function readCollection<T>(payload: unknown): readonly T[] {
  if (Array.isArray(payload)) return payload as readonly T[];
  if (
    payload &&
    typeof payload === 'object' &&
    'results' in payload &&
    Array.isArray((payload as { results?: unknown }).results)
  ) {
    return (payload as { results: readonly T[] }).results;
  }
  throw new Error('Operational status response did not contain a collection.');
}
