export interface DashboardMetric {
  readonly label: string;
  readonly value: number;
  readonly detail: string;
  readonly accent: string;
}

export interface AttentionItem {
  readonly label: string;
  readonly value: number;
  readonly detail: string;
  readonly tone: string;
}

export interface DataSummaryItem {
  readonly label: string;
  readonly value: number;
}

export interface NetworkItem {
  readonly active_location_count: number;
  readonly active_patient_count: number;
  readonly active_practitioner_count: number;
  readonly active_user_count: number;
  readonly country_code: string;
  readonly id: string;
  readonly name: string;
  readonly slug: string;
  readonly status: string;
  readonly time_zone: string;
}

export interface HQOverview {
  readonly attention_items: readonly AttentionItem[];
  readonly data_summary: readonly DataSummaryItem[];
  readonly generated_at: string;
  readonly is_platform_overview: boolean;
  readonly metrics: readonly DashboardMetric[];
  readonly network_items: readonly NetworkItem[];
  readonly scope_description: string;
  readonly scope_label: string;
  readonly tenant_id: string;
  readonly tenant_name: string;
  readonly user_name: string;
}

export class HQApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'HQApiError';
  }
}

export async function loadHQOverview(signal?: AbortSignal): Promise<HQOverview> {
  const request: RequestInit = {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  };
  if (signal) request.signal = signal;

  const response = await fetch('/api/hq/overview/', request);
  if (!response.ok) {
    throw new HQApiError(response.status, `HQ overview request failed with ${response.status}.`);
  }
  return (await response.json()) as HQOverview;
}

/* ────────────────────────────────────────────────────────────────────────────
   Workbench collections
   
   The overview above is one aggregate call. These reach the individual
   collections so a section can show real rows rather than a count.
   
   Money arrives as strings and stays as strings. The backend serialises
   decimals as strings precisely because JSON's only number type is a binary
   float, and parsing them here would undo that -- 22000.00 becomes
   21999.999999999996 and a total that balanced on the server stops balancing on
   the screen. Formatting for display is a string operation.
   ──────────────────────────────────────────────────────────────────────────── */

/** A decimal amount, carried as text. Never parsed into a number. */
export type Money = string;

export interface Paginated<T> {
  readonly results?: readonly T[];
}

/** Rows from a collection, whether or not pagination is switched on. */
export function collectionRows<T>(body: readonly T[] | Paginated<T>): readonly T[] {
  if (Array.isArray(body)) return body;
  return (body as Paginated<T>).results ?? [];
}

async function getCollection<T>(path: string, signal?: AbortSignal): Promise<readonly T[]> {
  const request: RequestInit = {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  };
  if (signal) request.signal = signal;

  const response = await fetch(path, request);
  if (!response.ok) {
    // Thrown, not swallowed into an empty list. A section that renders "0
    // claims" because the request failed is worse than one that says it could
    // not load: the first is believed.
    throw new HQApiError(response.status, `${path} failed with ${response.status}.`);
  }
  return collectionRows<T>(await response.json());
}

/* ── insurance ─────────────────────────────────────────────────────────────── */

export interface InsuranceClaim {
  readonly id: string;
  readonly claim_number: string;
  readonly insurer_code: string;
  /** Masked to its last four digits by the server. */
  readonly membership_number: string;
  /** Four independent dimensions. Never collapse these into one status. */
  readonly submission_state: string;
  readonly adjudication_state: string;
  readonly payment_state: string;
  readonly reconciliation_state: string;
  readonly claimed_gross_amount: Money;
  readonly approved_amount: Money;
  readonly patient_copay_amount: Money;
  readonly insurer_payable_amount: Money;
  readonly paid_amount: Money;
  readonly outstanding_amount: Money;
  readonly is_receivable: boolean;
  readonly currency: string;
}

export interface Insurer {
  readonly id: string;
  readonly code: string;
  readonly name: string;
  readonly integration_adapter: string;
  readonly environment: string;
  readonly status: string;
  /** Whether an adapter is actually implemented, not merely configured. */
  readonly adapter_registered: boolean;
}

export const loadInsurers = (signal?: AbortSignal) =>
  getCollection<Insurer>('/api/insurance/insurers/', signal);

/** Claims the insurer agreed to pay and has not paid. The money owed. */
export const loadApprovedUnpaidClaims = (signal?: AbortSignal) =>
  getCollection<InsuranceClaim>('/api/insurance/claims/approved-unpaid/', signal);

/**
 * Sent, acknowledged, still undecided.
 *
 * Deliberately a separate call from approved-unpaid: one is chased with the
 * insurer, the other is chased for payment, and showing them together is how
 * transport acceptance starts looking like a debt.
 */
export const loadClaimsAwaitingDecision = (signal?: AbortSignal) =>
  getCollection<InsuranceClaim>('/api/insurance/claims/awaiting-decision/', signal);

/** Everything blocked on this end rather than on the insurer. */
export const loadClaimsNeedingAttention = (signal?: AbortSignal) =>
  getCollection<InsuranceClaim>('/api/insurance/claims/needs-attention/', signal);

/* ── pricing ───────────────────────────────────────────────────────────────── */

export interface PriceBookSummary {
  readonly id: string;
  readonly code: string;
  readonly name: string;
  readonly currency: string;
  readonly price_type: string;
  readonly scope_type: string;
  readonly is_active: boolean;
  /** Null when the book is configured but has nothing a till could charge. */
  readonly live_version: number | null;
}

export const loadPriceBooks = (signal?: AbortSignal) =>
  getCollection<PriceBookSummary>('/api/pricing/books/', signal);

/* ── shift and cash control ────────────────────────────────────────────────── */

export interface RegisterSessionSummary {
  readonly id: string;
  readonly register_code: string;
  readonly business_date: string;
  readonly state: string;
  readonly opened_at: string;
  readonly opened_by_username: string;
  readonly closed_at: string | null;
  readonly forced_closure: boolean;
  readonly forced_closure_reason: string;
  /** The report is the authority on closure, not the session's own state. */
  readonly has_final_report: boolean;
}

export interface ShiftReportSummary {
  readonly id: string;
  readonly report_number: string;
  readonly report_type: 'X' | 'Z';
  readonly register_code: string;
  readonly business_date: string;
  readonly generated_at: string;
  readonly generated_by_username: string;
  readonly closure_type: string;
  readonly closure_reason: string;
  readonly reprint_count: number;
  /** The frozen figures as counted and signed. Rendered, never recomputed. */
  readonly snapshot: ShiftReportSnapshot;
}

export interface ShiftReportSnapshot {
  readonly cash?: {
    readonly opening?: Money;
    readonly cash_sales?: Money;
    readonly cash_in?: Money;
    readonly cash_out?: Money;
    readonly cash_refunds?: Money;
    readonly expected_closing?: Money;
  };
  readonly variance?: {
    readonly declared?: Money;
    readonly expected?: Money;
    readonly difference?: Money;
    readonly classification?: string;
    readonly requires_explanation?: boolean;
  } | null;
}

/** Registers currently trading. Checked at close of business. */
export const loadOpenRegisterSessions = (signal?: AbortSignal) =>
  getCollection<RegisterSessionSummary>('/api/pos/shift/sessions/open/', signal);

/** Z reports whose counted cash did not match expected. */
export const loadCashVariances = (signal?: AbortSignal) =>
  getCollection<ShiftReportSummary>('/api/pos/shift/reports/variances/', signal);

/** Closures performed by somebody other than the accountable operator. */
export const loadForcedClosures = (signal?: AbortSignal) =>
  getCollection<ShiftReportSummary>('/api/pos/shift/reports/forced-closures/', signal);

/* ── display helpers ───────────────────────────────────────────────────────── */

/**
 * Format a decimal string for display without going through a JS number.
 *
 * `Number(value).toFixed(2)` is the obvious implementation and it is wrong for
 * exactly the reason the backend sends strings: it round-trips through a binary
 * float. It also turns an unparseable value into the string "NaN", which is
 * then rendered onto a money field as though it were an amount.
 */
export function formatMoney(value: Money | null | undefined, currency = 'KES'): string {
  const text = (value ?? '').trim();
  if (text === '') return '—';
  if (!/^-?\d+(\.\d+)?$/.test(text)) return '—';

  const negative = text.startsWith('-');
  const [whole = '0', fraction = ''] = text.replace('-', '').split('.');
  const padded = (fraction + '00').slice(0, 2);
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  // Sign after the currency: "KES -50.00" sits more naturally beside
  // "KES 3,000.00" in a variance column than "-KES 50.00" does.
  return `${currency} ${negative ? '-' : ''}${grouped}.${padded}`;
}

/**
 * Whether a variance needs somebody to explain it.
 *
 * Read from the report's own snapshot rather than recomputed from declared and
 * expected: the snapshot is what was signed, and a UI that recalculates can
 * disagree with the paper the operator is holding.
 */
export function varianceNeedsExplanation(report: ShiftReportSummary): boolean {
  return report.snapshot?.variance?.requires_explanation === true;
}
