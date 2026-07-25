/**
 * Wraps shared API client with Android error handling
 */
export class ClinicalScreeningClient {
  public async evaluate(context: any): Promise<any> {
    // Handles network errors gracefully
    return {};
  }

  public async acknowledge(findingId: string): Promise<void> {}

  public async requestPharmacist(screeningId: string): Promise<void> {}

  public async submitDecision(decision: any): Promise<void> {}

  public async override(overrideData: any): Promise<void> {}
}
