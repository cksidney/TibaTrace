import { ControlledVerifyResponse, PosDispensingClient } from './types.js';

export class ControlledMedicineWorkflow {
  private client: PosDispensingClient;

  constructor(client: PosDispensingClient) {
    this.client = client;
  }

  async verifyControlledAuthority(episodeId: string, practitionerId: string, collectorIdNumber: string, witnessId?: string): Promise<ControlledVerifyResponse> {
    return this.client.verifyControlled(episodeId, {
      practitioner_id: practitionerId,
      collector_id_number: collectorIdNumber,
      witness_id: witnessId,
    });
  }
}
