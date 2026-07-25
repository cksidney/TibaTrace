/**
 * Android-specific UI state types for Drug Interaction Plugin
 */
export interface AndroidDrugInteractionState {
  isActive: boolean;
  screeningInProgress: boolean;
  currentScreening: any | null;
  pendingFindings: any[];
  pharmacistModalOpen: boolean;
  offlineState: any;
  lastSyncAt: Date | null;
}

export type AndroidAlertLevel = 'INFO' | 'CAUTION' | 'PHARMACIST' | 'BLOCKED';

export type AndroidAuthMethod = 'PIN' | 'PASSWORD' | 'BIOMETRIC';

export type AndroidPrinterTarget = 'RECEIPT' | 'LABEL' | 'COUNSELLING_SHEET';
