/**
 * Windows-specific UI state types for Drug Interaction Plugin
 */
export interface WindowsDrugInteractionState {
  isActive: boolean;
  screeningInProgress: boolean;
  currentScreening: any | null;
  pendingFindings: any[];
  pharmacistModalOpen: boolean;
  offlineState: any;
  lastSyncAt: Date | null;
}

export type WindowsAlertLevel = 'INFO' | 'CAUTION' | 'PHARMACIST' | 'BLOCKED';

export type WindowsShortcutKey = 'F6_CLINICAL_SAFETY' | 'F7_REQUEST_PHARMACIST' | 'F8_MEDICATION_HISTORY';

export type WindowsPrinterTarget = 'RECEIPT' | 'LABEL' | 'COUNSELLING_SHEET';
