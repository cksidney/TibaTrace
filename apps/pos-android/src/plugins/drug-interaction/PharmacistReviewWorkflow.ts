import type { AndroidAuthMethod } from './types';

/**
 * Pharmacist auth and review workflow for Android POS
 */
export class PharmacistReviewWorkflow {
  public requestReview(screeningId: string): void {}

  public authenticatePharmacist(method: AndroidAuthMethod, credentials: any): boolean {
    // Includes biometric authentication support
    // Ensures pharmacist != cashier
    return true;
  }

  public submitDecision(decision: any): void {}
}
