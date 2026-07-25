import { DeviceTelemetryDTO, PosDispensingClient } from './types.js';

export class DeviceHealthMonitor {
  private client: PosDispensingClient;
  private deviceId: string;

  constructor(client: PosDispensingClient, deviceId: string = 'WIN-POS-01') {
    this.client = client;
    this.deviceId = deviceId;
  }

  async sendTelemetry(telemetry: Partial<DeviceTelemetryDTO>): Promise<DeviceTelemetryDTO> {
    const payload: DeviceTelemetryDTO = {
      device_id: this.deviceId,
      device_type: 'TERMINAL',
      status: 'OK',
      printer_paper_level: 'OK',
      scanner_connected: true,
      cash_drawer_open: false,
      network_latency_ms: 12,
      storage_used_pct: 35,
      ...telemetry,
    };
    return this.client.recordTelemetry(payload);
  }
}
