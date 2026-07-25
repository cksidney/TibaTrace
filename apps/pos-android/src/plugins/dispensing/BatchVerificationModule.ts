import { BatchVerificationResponse, PosDispensingClient } from './types.js';

export class BatchVerificationModule {
  private client: PosDispensingClient;

  constructor(client: PosDispensingClient) {
    this.client = client;
  }

  async verifyCameraScan(skuId: string, cameraBarcodeData: string): Promise<BatchVerificationResponse> {
    let batchNumber = cameraBarcodeData.trim();
    let expiryDate: string | null = null;

    if (cameraBarcodeData.includes('|')) {
      const parts = cameraBarcodeData.split('|');
      batchNumber = parts[0].trim();
      expiryDate = parts[1] ? parts[1].trim() : null;
    }

    return this.client.verifyBatch({
      sku_id: skuId,
      batch_number: batchNumber,
      expiry_date: expiryDate,
      quantity_scanned: '1',
    });
  }
}
