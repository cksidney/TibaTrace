import { PaymentProcessResponse, PaymentTenderType, PosDispensingClient } from './types.js';

export class PaymentOrchestrationModule {
  private client: PosDispensingClient;

  constructor(client: PosDispensingClient) {
    this.client = client;
  }

  async processTender(episodeId: string, tenderType: PaymentTenderType, paidAmount: string, reference: string = ''): Promise<PaymentProcessResponse> {
    return this.client.processPayment(episodeId, {
      tender_type: tenderType,
      paid_amount: paidAmount,
      payment_reference: reference,
    });
  }
}
