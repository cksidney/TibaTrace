export interface PosRegisterDTO {
  readonly id: string;
  readonly code: string;
  readonly name: string;
  readonly branch_code: string;
  readonly device_id: string;
  readonly currency: string;
  readonly state: string;
  readonly expected_float: string;
  readonly last_synchronised_at: string | null;
}

export interface BusinessDayDTO {
  readonly id: string;
  readonly branch_code: string;
  readonly business_date: string;
  readonly state: string;
  readonly opened_at: string;
  readonly closed_at: string | null;
  readonly accepts_transactions: boolean;
  readonly reopen_reason: string;
}

export interface OperatorShiftDTO {
  readonly id: string;
  readonly operator_id: string;
  readonly operator_username: string;
  readonly state: 'OPEN' | 'HANDOVER_REQUESTED' | 'CLOSED' | 'FORCE_CLOSED';
  readonly started_at: string;
  readonly ended_at: string | null;
  readonly handed_over_to_username: string;
  readonly close_reason: string;
}

export interface RegisterSessionDTO {
  readonly id: string;
  readonly register_code: string;
  readonly business_date: string;
  readonly state: 'OPEN' | 'CLOSING' | 'CLOSED';
  readonly opened_at: string;
  readonly opened_by_username: string;
  readonly closed_at: string | null;
  readonly closed_by_username: string;
  readonly forced_closure: boolean;
  readonly forced_closure_reason: string;
  readonly has_final_report: boolean;
  readonly operator_shifts: readonly OperatorShiftDTO[];
}

export interface DeviceHealthDTO {
  readonly id: string;
  readonly device_id: string;
  readonly device_type: string;
  readonly status: 'OK' | 'WARNING' | 'ERROR' | 'OFFLINE';
  readonly printer_paper_level: string;
  readonly scanner_connected: boolean;
  readonly cash_drawer_open: boolean;
  readonly network_latency_ms: number;
  readonly battery_level_pct: number | null;
  readonly storage_used_pct: number;
}

export type OperationalReadiness = 'READY' | 'ATTENTION' | 'UNASSIGNED';

export interface PosOperationalContext {
  readonly readiness: OperationalReadiness;
  readonly register: PosRegisterDTO | null;
  readonly businessDay: BusinessDayDTO | null;
  readonly registerSession: RegisterSessionDTO | null;
  readonly operatorShift: OperatorShiftDTO | null;
  readonly deviceHealth: DeviceHealthDTO | null;
  readonly notices: readonly string[];
}

export interface PosOperationalRuntimeDTO {
  readonly readiness: OperationalReadiness;
  readonly register: PosRegisterDTO | null;
  readonly business_day: BusinessDayDTO | null;
  readonly register_session: RegisterSessionDTO | null;
  readonly operator_shift: OperatorShiftDTO | null;
  readonly device_health: DeviceHealthDTO | null;
  readonly notices: readonly string[];
  readonly allowed_actions: readonly string[];
  readonly closure_eligibility: {
    readonly eligible: boolean;
    readonly blocking_reasons: readonly string[];
  };
}

export interface CashDeclarationDTO {
  readonly id: string;
  readonly kind: 'OPENING' | 'CLOSING';
  readonly declared_amount: string;
  readonly currency: string;
  readonly denominations: Readonly<Record<string, number>>;
  readonly attempt: number;
  readonly declared_by_username: string;
  readonly confirmed_at: string | null;
  readonly is_confirmed: boolean;
  readonly reason: string;
}

export interface CashMovementDTO {
  readonly id: string;
  readonly kind: string;
  readonly amount: string;
  readonly signed_amount: string;
  readonly affects_expected_cash: boolean;
  readonly currency: string;
  readonly reason_code: string;
  readonly description: string;
  readonly reference: string;
  readonly created_by_username: string;
  readonly approved_by_username: string;
  readonly approved_at: string | null;
  readonly created_at: string;
}

export interface ShiftReportSnapshotDTO {
  readonly period_start: string;
  readonly generated_at: string;
  readonly currency: string;
  readonly cash: {
    readonly opening: string;
    readonly cash_sales: string;
    readonly cash_in: string;
    readonly cash_out: string;
    readonly cash_refunds: string;
    readonly expected_closing: string;
  };
  readonly tenders: {
    readonly by_type: Readonly<Record<string, string>>;
    readonly cash_total: string;
    readonly non_cash_total: string;
    readonly grand_total: string;
  };
  readonly cash_movements: readonly {
    readonly kind: string;
    readonly amount: string;
    readonly affects_expected_cash: boolean;
    readonly reference: string;
  }[];
  readonly variance: {
    readonly declared: string;
    readonly expected: string;
    readonly difference: string;
    readonly classification: string;
    readonly requires_explanation: boolean;
  } | null;
}

export interface ShiftReportDTO {
  readonly id: string;
  readonly report_number: string;
  readonly report_type: 'X' | 'Z';
  readonly register_code: string;
  readonly business_date: string;
  readonly period_start: string;
  readonly generated_at: string;
  readonly generated_by_username: string;
  readonly closure_type: 'NORMAL' | 'FORCED';
  readonly closure_reason: string;
  readonly approved_by_username: string;
  readonly snapshot: ShiftReportSnapshotDTO;
  readonly exceptions: readonly { readonly code: string; readonly message: string }[];
  readonly reprint_count: number;
}

export interface RegisterOpeningResultDTO {
  readonly register: PosRegisterDTO;
  readonly register_session: RegisterSessionDTO;
  readonly operator_shift: OperatorShiftDTO;
  readonly opening_declaration: CashDeclarationDTO;
}

export interface HandoverAcceptanceDTO {
  readonly outgoing_shift: OperatorShiftDTO;
  readonly operator_shift: OperatorShiftDTO;
}
