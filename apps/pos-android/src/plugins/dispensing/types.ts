export * from '@dawatrace/shared/dispensing/index.js';

export interface AndroidDispensingUIConfig {
  touchMode: boolean;
  cameraScannerEnabled: boolean;
  biometricAuthEnabled: boolean;
  handheldVerificationMode: boolean;
  batteryLevelAlertThresholdPct: number;
}
