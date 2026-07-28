/**
 * TibaTrace POS Clinical Screening — API Client
 *
 * Typed API client methods for POS clinical screening endpoints.
 * Platform-neutral — used by both Windows and Android POS clients.
 */

import { resolveFetcher } from '../auth/fetcher.js';

import type {
  PosClinicalScreeningRequest,
  PosClinicalScreeningResult,
  PosClinicalAcknowledgement,
  PosPharmacistReviewRequest,
  PosPharmacistDecision,
  PosClinicalOverrideApproval,
  PosClinicalOverrideHistory,
  PosClinicalOverrideRejection,
  PosClinicalOverrideRequest,
  PosClinicalOverrideRevocation,
  PosClinicalSyncRecord,
  PosOfflineClinicalPackage,
  PosClinicalErrorResponse,
  PosClinicalError,
} from "./types.js";

// ─── API Configuration ──────────────────────────────────────────────────────────

export interface PosClinicalApiConfig {
  baseUrl: string;
  tenantId: string;
  authToken: string;
  fetcher?: typeof fetch;
  timeout?: number;
  retryCount?: number;
}

// ─── API Response Wrapper ───────────────────────────────────────────────────────

export interface ApiResponse<T> {
  ok: boolean;
  status: number;
  data?: T;
  error?: PosClinicalErrorResponse;
}

// ─── Typed API Error ────────────────────────────────────────────────────────────

export class PosClinicalApiError extends Error {
  constructor(
    public readonly errorCode: PosClinicalError,
    public readonly statusCode: number,
    message: string,
    public readonly details?: Record<string, unknown>
  ) {
    super(message);
    this.name = "PosClinicalApiError";
  }
}

// ─── API Client ─────────────────────────────────────────────────────────────────

const BASE_PATH = "/api/pos/clinical-screening";

/**
 * Evaluate clinical screening for a POS transaction basket.
 * Calls POST /api/pos/clinical-screening/evaluate/
 */
export async function evaluatePosClinicalScreening(
  config: PosClinicalApiConfig,
  request: PosClinicalScreeningRequest
): Promise<ApiResponse<PosClinicalScreeningResult>> {
  return apiPost<PosClinicalScreeningResult>(
    config,
    `${BASE_PATH}/evaluate/`,
    request
  );
}

/**
 * Retrieve an existing clinical screening result.
 * Calls GET /api/pos/clinical-screening/{screeningId}/
 */
export async function getPosClinicalScreening(
  config: PosClinicalApiConfig,
  screeningId: string
): Promise<ApiResponse<PosClinicalScreeningResult>> {
  return apiGet<PosClinicalScreeningResult>(
    config,
    `${BASE_PATH}/${screeningId}/`
  );
}

/**
 * Acknowledge a clinical finding (cashier action for low-severity).
 * Calls POST /api/pos/clinical-screening/{screeningId}/acknowledge/
 */
export async function acknowledgePosClinicalFinding(
  config: PosClinicalApiConfig,
  screeningId: string,
  acknowledgement: PosClinicalAcknowledgement
): Promise<ApiResponse<PosClinicalScreeningResult>> {
  return apiPost<PosClinicalScreeningResult>(
    config,
    `${BASE_PATH}/${screeningId}/acknowledge/`,
    acknowledgement
  );
}

/**
 * Request pharmacist review for a screening.
 * Calls POST /api/pos/clinical-screening/{screeningId}/request-pharmacist/
 */
export async function requestPosPharmacistReview(
  config: PosClinicalApiConfig,
  screeningId: string,
  request: PosPharmacistReviewRequest
): Promise<ApiResponse<{ requestId: string; status: string }>> {
  return apiPost(
    config,
    `${BASE_PATH}/${screeningId}/request-pharmacist/`,
    request
  );
}

/**
 * Submit a pharmacist review decision.
 * Calls POST /api/pos/clinical-screening/{screeningId}/pharmacist-review/
 */
export async function submitPosPharmacistDecision(
  config: PosClinicalApiConfig,
  screeningId: string,
  decision: PosPharmacistDecision
): Promise<ApiResponse<PosClinicalScreeningResult>> {
  return apiPost<PosClinicalScreeningResult>(
    config,
    `${BASE_PATH}/${screeningId}/pharmacist-review/`,
    decision
  );
}

/**
 * Request a governed clinical override for a finding.
 * Calls POST /api/pos/clinical-screening/overrides/
 */
export async function requestPosClinicalOverride(
  config: PosClinicalApiConfig,
  request: PosClinicalOverrideRequest
): Promise<ApiResponse<PosClinicalOverrideHistory>> {
  return apiPost<PosClinicalOverrideHistory>(
    config,
    `${BASE_PATH}/overrides/`,
    request
  );
}

/** Move a requested override into pharmacist review. */
export async function startPosClinicalOverrideReview(
  config: PosClinicalApiConfig,
  overrideId: string,
): Promise<ApiResponse<PosClinicalOverrideHistory>> {
  return apiPost<PosClinicalOverrideHistory>(config, `${BASE_PATH}/overrides/${overrideId}/start-review/`, {});
}

/** Approve a requested override with a bounded clinical rationale. */
export async function approvePosClinicalOverride(
  config: PosClinicalApiConfig,
  overrideId: string,
  approval: PosClinicalOverrideApproval,
): Promise<ApiResponse<PosClinicalOverrideHistory>> {
  return apiPost<PosClinicalOverrideHistory>(config, `${BASE_PATH}/overrides/${overrideId}/approve/`, approval);
}

/** Reject a requested override while retaining the immutable request history. */
export async function rejectPosClinicalOverride(
  config: PosClinicalApiConfig,
  overrideId: string,
  rejection: PosClinicalOverrideRejection,
): Promise<ApiResponse<PosClinicalOverrideHistory>> {
  return apiPost<PosClinicalOverrideHistory>(config, `${BASE_PATH}/overrides/${overrideId}/reject/`, rejection);
}

/** Revoke an approved override and reopen the clinical blocker. */
export async function revokePosClinicalOverride(
  config: PosClinicalApiConfig,
  overrideId: string,
  revocation: PosClinicalOverrideRevocation,
): Promise<ApiResponse<PosClinicalOverrideHistory>> {
  return apiPost<PosClinicalOverrideHistory>(config, `${BASE_PATH}/overrides/${overrideId}/revoke/`, revocation);
}

/**
 * Get the current rule set version for the tenant.
 * Calls GET /api/pos/clinical-screening/ruleset-version/
 */
export async function getPosClinicalRuleSetVersion(
  config: PosClinicalApiConfig
): Promise<
  ApiResponse<{ version: string; ruleSetVersion: string; generatedAt: string }>
> {
  return apiGet(config, `${BASE_PATH}/ruleset-version/`);
}

/**
 * Download the offline clinical rule package.
 * Calls GET /api/pos/clinical-screening/offline-package/
 */
export async function downloadPosOfflineClinicalPackage(
  config: PosClinicalApiConfig
): Promise<ApiResponse<PosOfflineClinicalPackage>> {
  return apiGet<PosOfflineClinicalPackage>(
    config,
    `${BASE_PATH}/offline-package/`
  );
}

/**
 * Synchronize offline clinical decisions to the server.
 * Calls POST /api/pos/clinical-screening/sync/
 */
export async function syncOfflineClinicalDecisions(
  config: PosClinicalApiConfig,
  records: PosClinicalSyncRecord[]
): Promise<
  ApiResponse<{
    synced: number;
    conflicts: number;
    failed: number;
    details: Array<{ syncId: string; status: string; error?: string }>;
  }>
> {
  return apiPost(config, `${BASE_PATH}/sync/`, { records });
}

// ─── HTTP Helpers ───────────────────────────────────────────────────────────────

async function apiGet<T>(
  config: PosClinicalApiConfig,
  path: string
): Promise<ApiResponse<T>> {
  const url = `${config.baseUrl}${path}`;
  const controller = new AbortController();
  const timeoutId = setTimeout(
    () => controller.abort(),
    config.timeout ?? 15000
  );

  try {
    const response = await resolveFetcher(config.fetcher)(url, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${config.authToken}`,
        "X-Tenant-ID": config.tenantId,
        Accept: "application/json",
      },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const errorBody = (await response
        .json()
        .catch(() => null)) as PosClinicalErrorResponse | null;
      return {
        ok: false,
        status: response.status,
        error: errorBody ?? { error: "SCREENING_NOT_FOUND" as PosClinicalError, message: response.statusText },
      };
    }

    const data = (await response.json()) as T;
    return { ok: true, status: response.status, data };
  } catch (err) {
    clearTimeout(timeoutId);
    const message = err instanceof Error ? err.message : "Network error";
    return {
      ok: false,
      status: 0,
      error: { error: "SCREENING_NOT_FOUND" as PosClinicalError, message },
    };
  }
}

async function apiPost<T>(
  config: PosClinicalApiConfig,
  path: string,
  body: unknown
): Promise<ApiResponse<T>> {
  const url = `${config.baseUrl}${path}`;
  const controller = new AbortController();
  const timeoutId = setTimeout(
    () => controller.abort(),
    config.timeout ?? 15000
  );

  try {
    const response = await resolveFetcher(config.fetcher)(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.authToken}`,
        "X-Tenant-ID": config.tenantId,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const errorBody = (await response
        .json()
        .catch(() => null)) as PosClinicalErrorResponse | null;
      return {
        ok: false,
        status: response.status,
        error: errorBody ?? { error: "CLINICAL_BLOCK" as PosClinicalError, message: response.statusText },
      };
    }

    const data = (await response.json()) as T;
    return { ok: true, status: response.status, data };
  } catch (err) {
    clearTimeout(timeoutId);
    const message = err instanceof Error ? err.message : "Network error";
    return {
      ok: false,
      status: 0,
      error: { error: "CLINICAL_BLOCK" as PosClinicalError, message },
    };
  }
}
