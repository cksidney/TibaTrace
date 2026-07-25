import { PosDispensingClient, CounsellingRecordRequest } from './types.js';

export class PatientCounsellingModule {
  private client: PosDispensingClient;

  constructor(client: PosDispensingClient) {
    this.client = client;
  }

  async recordCounselling(episodeId: string, details: CounsellingRecordRequest): Promise<{ status: string; counselling_id: string }> {
    return this.client.recordCounselling(episodeId, details);
  }
}
