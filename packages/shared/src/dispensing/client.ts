import { classifyError, PosApiError } from './errors.js';
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

const DEFAULT_TIMEOUT_MS = 15000;

/**
 * Typed client for the POS dispensing API.
 *
 * Every method returns what the server said. Nothing here mutates a local copy
 * of an episode on success: a POS that marks a sale paid in its own memory will
 * eventually tell a pharmacist that money was taken when it was not.
 */
export class PosDispensingClient {
  private baseUrl: string;
  private token: string;
  private timeoutMs: number;

  constructor(
    baseUrl: string = '/api/pos/dispensing',
    token: string = '',
    timeoutMs: number = DEFAULT_TIMEOUT_MS,
  ) {
    this.baseUrl = baseUrl;
    this.token = token;
    this.timeoutMs = timeoutMs;
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...(options.headers as Record<string, string>),
    };
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...options,
        headers,
        credentials: 'include',
        signal: controller.signal,
      });
    } catch (cause) {
      // A timeout or dropped connection leaves the outcome genuinely unknown.
      // Surfaced as such rather than as a failure, because for a write the
      // server may well have applied it -- the caller must re-read state, not
      // assume it did not happen.
      throw new PosApiError(
        'NETWORK_UNAVAILABLE',
        'The server could not be reached. The outcome of this request is unknown.',
        0,
        cause,
      );
    } finally {
      clearTimeout(timer);
    }

    const text = await response.text();
    let payload: unknown = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }
    }
    if (!response.ok) {
      throw classifyError(response.status, payload);
    }
    return payload as T;
  }

  async getQueue(branchId?: string, status?: string): Promise<DispensingEpisodeDTO[]> {
    const params = new URLSearchParams();
    if (branchId) params.append('branch', branchId);
    if (status) params.append('status', status);
    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request<DispensingEpisodeDTO[]>(`/episodes/queue/${query}`);
  }

  /** Re-read one episode. The workflow calls this after every write. */
  async getEpisode(episodeId: string): Promise<DispensingEpisodeDTO> {
    return this.request<DispensingEpisodeDTO>(`/episodes/${episodeId}/`);
  }

  async transitionState(
    episodeId: string,
    req: { new_status: string; notes?: string },
  ): Promise<DispensingEpisodeDTO> {
    return this.request<DispensingEpisodeDTO>(`/episodes/${episodeId}/transition-state/`, {
      method: 'POST',
      body: JSON.stringify(req),
    });
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
