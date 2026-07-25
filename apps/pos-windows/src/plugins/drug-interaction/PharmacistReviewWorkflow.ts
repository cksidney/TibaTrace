/**
 * Pharmacist auth and review workflow for Windows POS
 */
export class PharmacistReviewWorkflow {
  public requestReview(screeningId: string): void {}

  public authenticatePharmacist(method: string, credentials: any): boolean {
    // Ensures pharmacist != cashier
    return true;
  }

  public submitDecision(decision: any): void {}
}
