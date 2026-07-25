import {
  DispensingEpisodeDTO,
  BatchVerificationRequest,
  BatchVerificationResponse,
  PaymentProcessRequest,
  PaymentProcessResponse,
  PartialDispenseRequest,
  PartialDispenseResponse,
  ControlledVerifyRequest,
  ControlledVerifyResponse,
  CounsellingRecordRequest,
  CollectionConfirmRequest,
  CollectionConfirmResponse,
  ShiftStartRequest,
  ShiftEndRequest,
  PosShiftRecordDTO,
  DeviceTelemetryDTO,
} from './types.js';

export class PosDispensingClient {
  private baseUrl: string;
  private token: string;

  constructor(baseUrl: string = '/api/pos/dispensing', token: string = '') {
    this.baseUrl = baseUrl;
    this.token = token;
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    };
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    const response = await fetch(`${this.baseUrl}${path}`, { ...options, headers });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API Error [${response.status}]: ${errorText}`);
    }
    return response.json() as Promise<T>;
  }

  async getQueue(branchId?: string, status?: string): Promise<DispensingEpisodeDTO[]> {
    const params = new URLSearchParams();
    if (branchId) params.append('branch', branchId);
    if (status) params.append('status', status);
    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request<DispensingEpisodeDTO[]>(`/episodes/queue/${query}`);
  }

  async verifyBatch(req: BatchVerificationRequest): Promise<BatchVerificationResponse> {
    return this.request<BatchVerificationResponse>('/episodes/verify-batch/', {
      method: 'POST',
      body: JSON.stringify(req),
    });
  }

  async processPayment(episodeId: string, req: PaymentProcessRequest): Promise<PaymentProcessResponse> {
    return this.request<PaymentProcessResponse>(`/episodes/${episodeId}/process-payment/`, {
      method: 'POST',
      body: JSON.stringify(req),
    });
  }

  async dispensePartial(episodeId: string, req: PartialDispenseRequest): Promise<PartialDispenseResponse> {
    return this.request<PartialDispenseResponse>(`/episodes/${episodeId}/dispense-partial/`, {
      method: 'POST',
      body: JSON.stringify(req),
    });
  }

  async verifyControlled(episodeId: string, req: ControlledVerifyRequest): Promise<ControlledVerifyResponse> {
    return this.request<ControlledVerifyResponse>(`/episodes/${episodeId}/verify-controlled/`, {
      method: 'POST',
      body: JSON.stringify(req),
    });
  }

  async recordCounselling(episodeId: string, req: CounsellingRecordRequest): Promise<{ status: string; counselling_id: string }> {
    return this.request<{ status: string; counselling_id: string }>(`/episodes/${episodeId}/record-counselling/`, {
      method: 'POST',
      body: JSON.stringify(req),
    });
  }

  async confirmCollection(episodeId: string, req: CollectionConfirmRequest): Promise<CollectionConfirmResponse> {
    return this.request<CollectionConfirmResponse>(`/episodes/${episodeId}/confirm-collection/`, {
      method: 'POST',
      body: JSON.stringify(req),
    });
  }

  async startShift(req: ShiftStartRequest): Promise<PosShiftRecordDTO> {
    return this.request<PosShiftRecordDTO>('/shifts/start/', {
      method: 'POST',
      body: JSON.stringify(req),
    });
  }

  async endShift(shiftId: string, req: ShiftEndRequest): Promise<PosShiftRecordDTO> {
    return this.request<PosShiftRecordDTO>(`/shifts/${shiftId}/end/`, {
      method: 'POST',
      body: JSON.stringify(req),
    });
  }

  async recordTelemetry(telemetry: DeviceTelemetryDTO): Promise<DeviceTelemetryDTO> {
    return this.request<DeviceTelemetryDTO>('/devices/telemetry/', {
      method: 'POST',
      body: JSON.stringify(telemetry),
    });
  }
}
