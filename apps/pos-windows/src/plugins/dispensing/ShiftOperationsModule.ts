import { PosShiftRecordDTO, PosDispensingClient } from './types.js';

export class ShiftOperationsModule {
  private client: PosDispensingClient;
  private currentShift: PosShiftRecordDTO | null = null;

  constructor(client: PosDispensingClient) {
    this.client = client;
  }

  async startShift(shiftNumber: string, controlledStartCount: number = 0): Promise<PosShiftRecordDTO> {
    const shift = await this.client.startShift({
      shift_number: shiftNumber,
      controlled_start_count: controlledStartCount,
    });
    this.currentShift = shift;
    return shift;
  }

  async endShift(controlledEndCount: number = 0, notes: string = ''): Promise<PosShiftRecordDTO> {
    if (!this.currentShift) {
      throw new Error('No active shift to end');
    }
    const shift = await this.client.endShift(this.currentShift.id, {
      controlled_end_count: controlledEndCount,
      declaration_notes: notes,
    });
    this.currentShift = null;
    return shift;
  }

  getCurrentShift(): PosShiftRecordDTO | null {
    return this.currentShift;
  }
}
