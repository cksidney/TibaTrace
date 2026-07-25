export type DispensingQueueState =
  | 'WAITING'
  | 'PREPARING'
  | 'AWAITING_PHARMACIST'
  | 'READY_FOR_PAYMENT'
  | 'PAID'
  | 'READY_FOR_COLLECTION'
  | 'COLLECTED'
  | 'PARTIALLY_DISPENSED'
  | 'ON_HOLD'
  | 'CANCELLED'
  | 'REJECTED';

export type PaymentTenderType =
  | 'CASH'
  | 'CARD'
  | 'MPESA'
  | 'SPLIT'
  | 'CREDIT_ACCOUNT'
  | 'INSTITUTIONAL';

export type LabelPrintFormat =
  | '70x40'
  | '58x40'
  | 'A4_MULTI';

export interface DispensingLineDTO {
  id: string;
  prescription_item: string;
  prescribed_sku: string;
  supplied_sku: string;
  inventory_batch: string;
  quantity_authorized: string;
  quantity_prepared: string;
  quantity_supplied: string;
  unit: string;
  batch_number_snapshot: string;
  expiry_date_snapshot: string;
  dosage_label_instructions: string;
  status: string;
}

export interface DispensingEpisodeDTO {
  id: string;
  dispensing_number: string;
  prescription: string;
  patient: string;
  branch: string;
  pharmacy_location: string;
  pharmacist: string;
  status: DispensingQueueState;
  initiated_at: string;
  completed_at?: string | null;
  payment_gate_state: string;
  payment_status: string;
  payment_reference: string;
  tender_type: PaymentTenderType;
  paid_amount: string;
  collector_name: string;
  collector_id_number: string;
  collector_phone: string;
  collector_relationship: string;
  collection_proof_type: string;
  collected_at?: string | null;
  controlled_witness?: string | null;
  controlled_authority_checked: boolean;
  counselling_status: string;
  notes: string;
  idempotency_key: string;
  lines: DispensingLineDTO[];
}

export interface BatchVerificationRequest {
  sku_id: string;
  batch_number: string;
  expiry_date?: string | null;
  quantity_scanned?: string;
}

export interface BatchVerificationResponse {
  valid: boolean;
  reason: string;
  sku_match: boolean;
  batch_found: boolean;
  release_status: string;
  is_recalled: boolean;
  is_expired: boolean;
  quantity_available: string;
}

export interface PaymentProcessRequest {
  tender_type: PaymentTenderType;
  paid_amount: string;
  payment_reference?: string;
}

export interface PaymentProcessResponse {
  success: boolean;
  episode_id: string;
  payment_status: string;
  payment_reference: string;
  tender_type: PaymentTenderType;
  paid_amount: string;
}

export interface PartialDispenseRequest {
  dispensing_line_id: string;
  quantity_supplied: string;
  reason?: string;
}

export interface PartialDispenseResponse {
  line_id: string;
  quantity_authorized: string;
  quantity_supplied: string;
  outstanding_balance: string;
  status: string;
}

export interface ControlledVerifyRequest {
  practitioner_id: string;
  collector_id_number: string;
  witness_id?: string | null;
}

export interface ControlledVerifyResponse {
  verified: boolean;
  authority_checked: boolean;
  collector_id_number: string;
  witness_id?: string | null;
}

export interface CounsellingRecordRequest {
  medicine_explained: boolean;
  dosage_explained: boolean;
  storage_explained: boolean;
  side_effects_discussed: boolean;
  interaction_advice_given: boolean;
  patient_acknowledged: boolean;
  notes?: string;
}

export interface CollectionConfirmRequest {
  collector_name: string;
  collector_id_number?: string;
  collector_phone?: string;
  collector_relationship?: string;
  collection_proof_type?: string;
  signature_ref?: string;
}

export interface CollectionConfirmResponse {
  status: string;
  supply_id: string;
  collected_at: string;
}

export interface ShiftStartRequest {
  shift_number: string;
  controlled_start_count: number;
  location_id?: string | null;
}

export interface ShiftEndRequest {
  controlled_end_count: number;
  declaration_notes?: string;
}

export interface PosShiftRecordDTO {
  id: string;
  shift_number: string;
  cashier?: string | null;
  pharmacist?: string | null;
  location?: string | null;
  started_at: string;
  ended_at?: string | null;
  status: 'OPEN' | 'CLOSED' | 'RECONCILED';
  controlled_stock_start_count: number;
  controlled_stock_end_count: number;
  discrepancy_declared: boolean;
  declaration_notes: string;
}

export interface DeviceTelemetryDTO {
  device_id: string;
  device_type: string;
  status: 'OK' | 'WARNING' | 'ERROR' | 'OFFLINE';
  printer_paper_level: string;
  scanner_connected: boolean;
  cash_drawer_open: boolean;
  network_latency_ms: number;
  battery_level_pct?: number | null;
  storage_used_pct: number;
}
