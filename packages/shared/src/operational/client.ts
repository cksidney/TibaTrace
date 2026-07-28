import { resolveFetcher } from '../auth/fetcher.js';

import type {
  BusinessDayDTO,
  CashDeclarationDTO,
  CashMovementDTO,
  DeviceHealthDTO,
  HandoverAcceptanceDTO,
  OperatorShiftDTO,
  PosRegisterDTO,
  PosOperationalRuntimeDTO,
  RegisterOpeningResultDTO,
  RegisterSessionDTO,
  ShiftReportDTO,
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

  async getRuntime(deviceId: string): Promise<PosOperationalRuntimeDTO> {
    return this.request<PosOperationalRuntimeDTO>(
      `/registers/runtime/?device_id=${encodeURIComponent(deviceId)}`,
    );
  }

  async getCashDeclarations(sessionId: string): Promise<readonly CashDeclarationDTO[]> {
    return this.collection<CashDeclarationDTO>(
      `/cash-declarations/?session=${encodeURIComponent(sessionId)}`,
    );
  }

  async getCashMovements(sessionId: string): Promise<readonly CashMovementDTO[]> {
    return this.collection<CashMovementDTO>(
      `/cash-movements/?session=${encodeURIComponent(sessionId)}`,
    );
  }

  async getReports(type?: 'X' | 'Z'): Promise<readonly ShiftReportDTO[]> {
    return this.collection<ShiftReportDTO>(`/reports/${type ? `?type=${type}` : ''}`);
  }

  async openRegister(
    registerId: string,
    input: {
      readonly deviceId: string;
      readonly openingAmount: string;
      readonly denominations: Readonly<Record<string, number>>;
    },
  ): Promise<RegisterOpeningResultDTO> {
    return this.command<RegisterOpeningResultDTO>(
      `/registers/${encodeURIComponent(registerId)}/open/`,
      {
        device_id: input.deviceId,
        opening_amount: input.openingAmount,
        denominations: input.denominations,
      },
    );
  }

  async recordCashMovement(input: {
    readonly deviceId: string;
    readonly kind: string;
    readonly amount: string;
    readonly reasonCode: string;
    readonly description?: string;
    readonly reference?: string;
  }): Promise<CashMovementDTO> {
    return this.command<CashMovementDTO>('/cash-movements/record/', {
      device_id: input.deviceId,
      kind: input.kind,
      amount: input.amount,
      reason_code: input.reasonCode,
      description: input.description ?? '',
      reference: input.reference ?? '',
    });
  }

  async approveCashMovement(movementId: string): Promise<CashMovementDTO> {
    return this.command<CashMovementDTO>(
      `/cash-movements/${encodeURIComponent(movementId)}/approve/`,
      {},
    );
  }

  async generateXReport(registerId: string, deviceId: string): Promise<ShiftReportDTO> {
    return this.command<ShiftReportDTO>(
      `/registers/${encodeURIComponent(registerId)}/x-report/`,
      { device_id: deviceId },
    );
  }

  async closeRegister(
    registerId: string,
    input: {
      readonly deviceId: string;
      readonly declaredAmount: string;
      readonly denominations: Readonly<Record<string, number>>;
      readonly reason?: string;
    },
  ): Promise<ShiftReportDTO> {
    return this.command<ShiftReportDTO>(
      `/registers/${encodeURIComponent(registerId)}/close/`,
      {
        device_id: input.deviceId,
        declared_amount: input.declaredAmount,
        denominations: input.denominations,
        reason: input.reason ?? '',
      },
    );
  }

  async requestHandover(shiftId: string, deviceId: string, reason = ''): Promise<OperatorShiftDTO> {
    return this.command<OperatorShiftDTO>(
      `/shifts/${encodeURIComponent(shiftId)}/request-handover/`,
      { device_id: deviceId, reason },
    );
  }

  async cancelHandover(shiftId: string, deviceId: string): Promise<OperatorShiftDTO> {
    return this.command<OperatorShiftDTO>(
      `/shifts/${encodeURIComponent(shiftId)}/cancel-handover/`,
      { device_id: deviceId },
    );
  }

  async acceptHandover(shiftId: string, deviceId: string): Promise<HandoverAcceptanceDTO> {
    return this.command<HandoverAcceptanceDTO>(
      `/shifts/${encodeURIComponent(shiftId)}/accept-handover/`,
      { device_id: deviceId },
    );
  }

  private async collection<T>(path: string): Promise<readonly T[]> {
    return readCollection<T>(await this.request<unknown>(path));
  }

  private async command<T>(path: string, body: object): Promise<T> {
    return this.request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.fetcher(`${this.baseUrl}${path}`, {
      ...init,
      credentials: 'include',
      headers: { Accept: 'application/json', ...(init.headers ?? {}) },
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as
        | { readonly detail?: string | readonly string[]; readonly error?: string }
        | null;
      const detail =
        typeof payload?.detail === 'string'
          ? payload.detail
          : Array.isArray(payload?.detail)
            ? payload.detail.join(' ')
            : undefined;
      throw new Error(
        payload?.error || detail || `Operational action failed with ${response.status}.`,
      );
    }
    return (await response.json()) as T;
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
