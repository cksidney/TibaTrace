/**
 * Mirrors DispensingEpisode.STATUS_CHOICES on the backend, which is the
 * authority. The previous version of this type declared WAITING,
 * AWAITING_PHARMACIST, COLLECTED and PARTIALLY_DISPENSED -- none of which the
 * server ever emits, so any client branching on them was dead code.
 */
export type DispensingQueueState =
  | 'DRAFT'
  | 'PREPARING'
  | 'CHECKING'
  | 'READY_FOR_PAYMENT'
  | 'PAID'
  | 'READY_FOR_COLLECTION'
  | 'READY_FOR_SUPPLY'
  | 'PARTIALLY_SUPPLIED'
  | 'SUPPLIED'
  | 'CLOSED'
  | 'ON_HOLD'
  | 'CANCELLED'
  | 'REJECTED'
  | 'REVERSED'
  | 'RETURNED';

/**
 * Canonical payment lifecycle for a dispensing episode. Mirrors
 * DispensingEpisode.PAYMENT_STATES on the backend, which is the authority.
 * Only NOT_REQUIRED, AUTHORIZED, PAID and WAIVED permit medicine supply --
 * PARTIALLY_PAID deliberately does not.
 */
export type PaymentState =
  | 'NOT_REQUIRED'
  | 'PENDING'
  | 'AUTHORIZED'
  | 'PARTIALLY_PAID'
  | 'PAID'
  | 'WAIVED'
  | 'FAILED'
  | 'CANCELLED'
  | 'REVERSAL_PENDING'
  | 'REVERSED'
  | 'REFUNDED';

/**
 * Tender types the server actually accepts, mirroring TENDER_TYPES in
 * pos_dispensing_api/serializers.py.
 *
 * Previously this union also declared SPLIT, CREDIT_ACCOUNT and INSTITUTIONAL.
 * The server rejects all three, so any client offering them would have produced
 * a payment the system could not settle. A tender belongs here only once its
 * settlement path exists.
 */
export type PaymentTenderType = 'CASH' | 'CARD' | 'MPESA';

/**
 * How the operator is paying, which is not the same as a tender type. SPLIT is
 * a UI mode that allocates across several tenders; it is never sent as one.
 */
export type PaymentMode = PaymentTenderType | 'SPLIT';

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
  payment_state: PaymentState;
  payment_reference: string;
  tender_type: PaymentTenderType;
  paid_amount: string;
  /**
   * Authoritative totals from the active PaymentIntent, or null when no intent
   * is open. `paid_amount` on the episode is a convenience mirror and must not
   * be shown as the amount due.
   */
  amount_due: string | null;
  amount_settled: string | null;
  amount_remaining: string | null;
  currency: string | null;
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
  /**
   * Required by the server. Must stay stable across retries of the *same*
   * attempt so a dropped connection cannot charge the patient twice; generate a
   * fresh one only for a genuinely new payment.
   */
  idempotency_key: string;
}

export interface PaymentProcessResponse {
  success: boolean;
  episode_id: string;
  payment_state: PaymentState;
  payment_reference: string;
  tender_type: PaymentTenderType;
  paid_amount: string;
  /** True when the server recognised a replay and did not take payment again. */
  replayed: boolean;
}

export interface PartialDispenseRequest {
  dispensing_line_id: string;
  quantity_supplied: string;
  reason?: string;
  idempotency_key: string;
}

export interface PartialDispenseResponse {
  supply_id: string;
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

/**
 * Mirrors CounsellingRecordSerializer. Every flag is optional on the wire
 * because the server declares a default for each.
 *
 * Note for the counselling UI: those server-side defaults are `True`, so an
 * empty body records that every topic was covered. The panel must therefore
 * send explicit values for what the pharmacist actually did rather than
 * omitting fields.
 */
export interface CounsellingRecordRequest {
  medicine_explained?: boolean;
  dosage_explained?: boolean;
  storage_explained?: boolean;
  side_effects_discussed?: boolean;
  interaction_advice_given?: boolean;
  patient_acknowledged?: boolean;
  notes?: string;
}

export interface CollectionConfirmRequest {
  collector_name: string;
  collector_id_number?: string;
  collector_phone?: string;
  collector_relationship?: string;
  collection_proof_type?: string;
  signature_ref?: string;
  idempotency_key: string;
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

/**
 * Payment states in which medicine supply is commercially permitted. Mirrors
 * DispensingEpisode.PAYMENT_STATES_PERMITTING_SUPPLY. PARTIALLY_PAID is
 * deliberately absent: part-payment must not release stock.
 *
 * This is a *display* helper for greying out controls. The server enforces the
 * real gate and rejects independently -- never treat this as authorisation.
 */
export const PAYMENT_STATES_PERMITTING_SUPPLY: readonly PaymentState[] = [
  'NOT_REQUIRED',
  'AUTHORIZED',
  'PAID',
  'WAIVED',
];

export function paymentPermitsSupply(state: PaymentState): boolean {
  return PAYMENT_STATES_PERMITTING_SUPPLY.includes(state);
}
