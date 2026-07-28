import { resolveFetcher } from '../auth/fetcher.js';

import type {
  RetailCatalogueItemDTO,
  RetailStoreDTO,
  RetailTransactionDTO,
  RetailTransactionLineDTO,
} from './types.js';

export class PosRetailClient {
  private readonly fetcher: typeof fetch;

  constructor(
    private readonly baseUrl = '/api/pos/retail',
    options: { readonly fetcher?: typeof fetch } = {},
  ) {
    this.fetcher = resolveFetcher(options.fetcher);
  }

  async stores(): Promise<readonly RetailStoreDTO[]> {
    return this.requestCollection<RetailStoreDTO>('/api/inventory/locations/');
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

  private async request<T>(path: string, method: string, body?: unknown): Promise<T> {
    const response = await this.fetcher(`${this.baseUrl}${path}`, {
      method,
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (response.status === 204) return undefined as T;
    if (!response.ok) throw new Error(await describeFailure(response));
    return (await response.json()) as T;
  }

  private async requestCollection<T>(path: string): Promise<readonly T[]> {
    const response = await this.fetcher(path, { credentials: 'include', headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(await describeFailure(response));
    const payload: unknown = await response.json();
    if (Array.isArray(payload)) return payload as readonly T[];
    if (payload && typeof payload === 'object' && Array.isArray((payload as { results?: unknown }).results)) {
      return (payload as { results: readonly T[] }).results;
    }
    throw new Error('The POS API returned an invalid collection.');
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
