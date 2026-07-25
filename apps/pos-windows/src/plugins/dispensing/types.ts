export * from '@dawatrace/shared/dispensing/index.js';

export interface WindowsDispensingUIConfig {
  shortcutKeys: {
    queueSwitch: 'F1';
    batchScan: 'F2';
    pharmacistAuth: 'F3';
    processPayment: 'F4';
    printLabel: 'F5';
    counselling: 'F6';
    collection: 'F7';
    shiftOps: 'F8';
  };
  barcodeScannerPrefix: string;
  barcodeScannerSuffix: string;
  autoPrintLabelsOnPayment: boolean;
  dualScreenDisplayEnabled: boolean;
}
