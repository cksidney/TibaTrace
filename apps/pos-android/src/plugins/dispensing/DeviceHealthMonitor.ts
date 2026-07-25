import { DeviceTelemetryDTO, PosDispensingClient } from './types.js';

export class DeviceHealthMonitor {
  private client: PosDispensingClient;
  private deviceId: string;

  constructor(client: PosDispensingClient, deviceId: string = 'AND-POS-01') {
    this.client = client;
    this.deviceId = deviceId;
  }

  async sendTelemetry(batteryPct: number = 85): Promise<DeviceTelemetryDTO> {
    const payload: DeviceTelemetryDTO = {
      device_id: this.deviceId,
      device_type: 'MOBILE_TERMINAL',
      status: 'OK',
      printer_paper_level: 'OK',
      scanner_connected: true,
      cash_drawer_open: false,
      network_latency_ms: 25,
      battery_level_pct: batteryPct,
      storage_used_pct: 42,
    };
    return this.client.recordTelemetry(payload);
  }
}
