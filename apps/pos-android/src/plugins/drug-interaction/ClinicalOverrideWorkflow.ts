/**
 * Override capture workflow for Android POS
 */
export class ClinicalOverrideWorkflow {
  public initiateOverride(findingId: string): void {}

  public validateCapability(pharmacistId: string, severity: string): boolean {
    // Requires capability check
    return true;
  }

  public recordOverride(overrideData: any): void {}
}
