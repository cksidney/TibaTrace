import { PartialDispenseResponse, PosDispensingClient } from './types.js';

export class PartialRepeatManager {
  private client: PosDispensingClient;

  constructor(client: PosDispensingClient) {
    this.client = client;
  }

  async dispenseStagedQuantity(episodeId: string, lineId: string, quantitySupplied: string, reason: string = ''): Promise<PartialDispenseResponse> {
    return this.client.dispensePartial(episodeId, {
      dispensing_line_id: lineId,
      quantity_supplied: quantitySupplied,
      reason,
    });
  }
}
