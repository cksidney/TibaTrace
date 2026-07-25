import type { WindowsAlertLevel } from './types';

/**
 * Alert rendering logic for Windows POS
 */
export class ClinicalAlertPresenter {
  public presentInformational(finding: any): void {
    // compact panel
  }

  public presentModerate(finding: any): void {
    // prominent warning
  }

  public presentBlocking(findings: any[]): void {
    // modal
  }
}
