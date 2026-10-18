import { resolveFetcher } from '../auth/fetcher.js';

import type {
  RetailCatalogueItemDTO,
  RetailStoreDTO,
  RetailTransactionDTO,
  RetailTransactionLineDTO,
  RetailRefundInput, RetailRefundRequestDTO, RetailCashRefundDTO,
} from './types.js';

export class PosRetailClient {
  private readonly fetcher: typeof fetch;

  constructor(
    private readonly baseUrl = '/api/pos/retail',
    options: { readonly fetcher?: typeof fetch } = {},
  ) {
    this.fetcher = resolveFetcher(options.fetcher);
  }

  async stores(deviceId = ''): Promise<readonly RetailStoreDTO[]> {
    return this.request(`/catalogue/stores/?device_id=${encodeURIComponent(deviceId)}`, 'GET');
  }

  async returnLocations(deviceId = ''): Promise<readonly RetailStoreDTO[]> {
    return this.request(`/catalogue/return-locations/?device_id=${encodeURIComponent(deviceId)}`, 'GET');
  }

  lookupReceipt(receiptNumber: string): Promise<RetailTransactionDTO> {
    return this.request(`/transactions/lookup-receipt/?receipt_number=${encodeURIComponent(receiptNumber)}`, 'GET');
  }

  requestRefund(transactionId: string, input: RetailRefundInput): Promise<RetailRefundRequestDTO> {
    return this.request(`/transactions/${transactionId}/request-refund/`, 'POST', input);
  }

  reviewRefund(transactionId: string, refundId: string, approve: boolean, reason = ''): Promise<RetailRefundRequestDTO> {
    return this.request(`/transactions/${transactionId}/${approve ? 'approve' : 'reject'}-refund/`, 'POST', {
      refund_request_id: refundId, reason,
    });
  }

  cashRefund(transactionId: string, refundId: string, deviceId: string, key: string, paymentReferences?: Readonly<Record<string, string>>): Promise<RetailCashRefundDTO> {
    return this.request(`/transactions/${transactionId}/cash-refund/`, 'POST', {
      refund_request_id: refundId, device_id: deviceId, idempotency_key: key,
      ...(paymentReferences ? { payment_references: paymentReferences } : {}),
    });
  }

  createDraft(input: { device_id: string; store_id: string }): Promise<RetailTransactionDTO> {
    return this.request('/transactions/draft/', 'POST', input);
  }

  getTransaction(transactionId: string): Promise<RetailTransactionDTO> {
    return this.request(`/transactions/${transactionId}/`, 'GET');
  }

  search(input: { device_id: string; store_id: string; query: string }): Promise<readonly RetailCatalogueItemDTO[]> {
    return this.request('/catalogue/search/', 'POST', input);
  }

  scan(transactionId: string, input: { device_id: string; barcode: string; quantity: string }): Promise<RetailTransactionLineDTO> {
    return this.request(`/transactions/${transactionId}/scan/`, 'POST', input);
  }

  addLine(transactionId: string, input: { device_id: string; sku_id: string; quantity: string }): Promise<RetailTransactionLineDTO> {
    return this.request(`/transactions/${transactionId}/add-line/`, 'POST', input);
  }

  setQuantity(transactionId: string, input: { device_id: string; line_id: string; quantity: string }): Promise<RetailTransactionLineDTO> {
    return this.request(`/transactions/${transactionId}/set-quantity/`, 'POST', input);
  }

  removeLine(transactionId: string, input: { device_id: string; line_id: string }): Promise<void> {
    return this.request(`/transactions/${transactionId}/remove-line/`, 'POST', input);
  }

  hold(transactionId: string, input: { device_id: string; reason: string }): Promise<RetailTransactionDTO> {
    return this.request(`/transactions/${transactionId}/hold/`, 'POST', input);
  }

  resume(transactionId: string, input: { device_id: string }): Promise<RetailTransactionDTO> {
    return this.request(`/transactions/${transactionId}/resume/`, 'POST', input);
  }

  cancel(transactionId: string, input: { device_id: string; reason: string }): Promise<RetailTransactionDTO> {
    return this.request(`/transactions/${transactionId}/cancel/`, 'POST', input);
  }

  readyForPayment(transactionId: string, input: { device_id: string }): Promise<RetailTransactionDTO> {
    return this.request(`/transactions/${transactionId}/ready-for-payment/`, 'POST', input);
  }

  settleCash(
    transactionId: string,
    input: { device_id: string; cash_received: string; idempotency_key: string },
  ): Promise<RetailTransactionDTO> {
    return this.request(`/transactions/${transactionId}/cash-settle/`, 'POST', {
      ...input,
      tender_type: 'CASH',
    });
  }

  private async request<T>(path: string, method: string, body?: unknown): Promise<T> {
    let response: Response;
    try { response = await this.fetcher(`${this.baseUrl}${path}`, {
      method,
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    }); } catch {
      throw new Error('Outcome unknown. Refresh the transaction before retrying and keep the original payment/refund key.');
    }
    if (response.status === 204) return undefined as T;
    if (!response.ok) throw new Error(await describeFailure(response));
    return (await response.json()) as T;
  }

}

async function describeFailure(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === 'string') return body;
    if (body && typeof body === 'object') {
      const detail = (body as { detail?: unknown }).detail;
      if (typeof detail === 'string') return detail;
      return Object.values(body as Record<string, unknown>).flat().join(' ');
    }
  } catch {
    return `POS request failed with ${response.status}.`;
  }
  return `POS request failed with ${response.status}.`;
}
