import { CollectionConfirmRequest, CollectionConfirmResponse, PosDispensingClient } from './types.js';

export class CollectionWorkflowModule {
  private client: PosDispensingClient;

  constructor(client: PosDispensingClient) {
    this.client = client;
  }

  async confirmCollection(episodeId: string, details: CollectionConfirmRequest): Promise<CollectionConfirmResponse> {
    return this.client.confirmCollection(episodeId, details);
  }
}
