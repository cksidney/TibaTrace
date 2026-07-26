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

export interface HQPatient {
  readonly consent_status: string;
  readonly full_name: string;
  readonly id: string;
  readonly is_active: boolean;
  readonly patient_number: string;
  readonly updated_at: string;
  readonly verification_status: string;
}

export interface HQPractitioner {
  readonly full_name: string;
  readonly id: string;
  readonly licence_status: string;
  readonly profession: string;
  readonly registration_number: string;
  readonly status: string;
  readonly verification_state: string;
}

export interface HQCustomer {
  readonly credit_status: string;
  readonly customer_number: string;
  readonly customer_type: string;
  readonly id: string;
  readonly legal_name: string;
  readonly risk_classification: string;
  readonly status: string;
}

export interface HQSku {
  readonly brand_name: string;
  readonly canonical_medicine_name: string;
  readonly default_barcode: string;
  readonly display_name: string;
  readonly id: string;
  readonly is_dispensable: boolean;
  readonly is_purchasable: boolean;
  readonly is_saleable: boolean;
  readonly sku_code: string;
  readonly status: string;
}

export interface HQSalesOrder {
  readonly currency: string;
  readonly customer_name: string;
  readonly id: string;
  readonly order_date: string;
  readonly order_number: string;
  readonly priority: number;
  readonly requested_delivery_date: string | null;
  readonly status: string;
  readonly total: Money;
}

export interface HQDispatch {
  readonly carrier: string;
  readonly customer_name: string;
  readonly dispatch_date: string | null;
  readonly dispatch_number: string;
  readonly expected_delivery_date: string | null;
  readonly id: string;
  readonly status: string;
}

export interface HQAuditEvent {
  readonly action: string;
  readonly actor: string;
  readonly correlation_id: string;
  readonly created_at: string;
  readonly id: string;
  readonly model_name: string;
  readonly object_id: string;
  readonly outcome: string;
}

export interface HQDocument {
  readonly content_type: string;
  readonly created_at: string;
  readonly id: string;
  readonly malware_scan_status: string;
  readonly original_name: string;
  readonly size_bytes: number;
}

export interface HQDomainEvent {
  readonly aggregate_type: string;
  readonly attempts: number;
  readonly created_at: string;
  readonly event_type: string;
  readonly id: string;
  readonly last_error: string;
  readonly status: string;
}

export interface HQNotification {
  readonly channel: string;
  readonly created_at: string;
  readonly id: string;
  readonly last_error: string;
  readonly recipient: string;
  readonly status: string;
  readonly template_code: string;
}

export interface HQCrosswalk {
  readonly created_at: string;
  readonly id: string;
  readonly migrated_at: string | null;
  readonly migration_batch: string;
  readonly source_entity_type: string;
  readonly source_system: string;
  readonly target_entity_type: string;
}

export type HQActionFieldType = 'checkbox' | 'number' | 'select' | 'text' | 'textarea';

export interface HQActionField {
  readonly default: boolean | number | string;
  readonly label: string;
  readonly name: string;
  readonly options: readonly string[];
  readonly required: boolean;
  readonly type: HQActionFieldType;
}

export interface HQBusinessAction {
  readonly confirm: string;
  readonly fields: readonly HQActionField[];
  readonly key: string;
  readonly label: string;
  readonly method: 'POST';
  readonly path: string;
  readonly tone: 'danger' | 'primary' | 'warning';
}

export interface HQWorkMetric {
  readonly label: string;
  readonly value: string;
}

export interface HQWorkItem {
  readonly actions: readonly HQBusinessAction[];
  readonly detail: string;
  readonly id: string;
  readonly metrics: readonly HQWorkMetric[];
  readonly reference: string;
  readonly status: string;
  readonly tenant_id: string;
  readonly tenant_name: string;
  readonly title: string;
}

export interface HQBusinessModule {
  readonly description: string;
  readonly domain: string;
  readonly key: string;
  readonly records: readonly HQWorkItem[];
  readonly title: string;
}

export interface HQWorkspaceData {
  readonly business_modules: readonly HQBusinessModule[];
  readonly generated_at: string;
  readonly people: {
    readonly counts: {
      readonly active_customers: number;
      readonly active_patients: number;
      readonly customers: number;
      readonly patients: number;
      readonly practitioners: number;
      readonly verified_practitioners: number;
    };
    readonly customers: readonly HQCustomer[];
    readonly patients: readonly HQPatient[];
    readonly practitioners: readonly HQPractitioner[];
  };
  readonly catalogue: {
    readonly counts: {
      readonly active_skus: number;
      readonly manufacturers: number;
      readonly skus: number;
      readonly substances: number;
    };
    readonly skus: readonly HQSku[];
  };
  readonly commerce: {
    readonly counts: {
      readonly deliveries: number;
      readonly dispatches: number;
      readonly open_orders: number;
      readonly orders: number;
      readonly quotations: number;
      readonly returns: number;
    };
    readonly dispatches: readonly HQDispatch[];
    readonly orders: readonly HQSalesOrder[];
  };
  readonly governance: {
    readonly counts: {
      readonly audit_events: number;
      readonly crosswalks: number;
      readonly documents: number;
      readonly domain_events: number;
      readonly failed_domain_events: number;
      readonly notifications: number;
      readonly pending_notifications: number;
    };
    readonly audit_events: readonly HQAuditEvent[];
    readonly crosswalks: readonly HQCrosswalk[];
    readonly documents: readonly HQDocument[];
    readonly domain_events: readonly HQDomainEvent[];
    readonly notifications: readonly HQNotification[];
  };
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

export async function loadHQWorkspace(signal?: AbortSignal): Promise<HQWorkspaceData> {
  const request: RequestInit = {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  };
  if (signal) request.signal = signal;

  const response = await fetch('/api/hq/workspace/', request);
  if (!response.ok) {
    throw new HQApiError(response.status, `HQ workspace request failed with ${response.status}.`);
  }
  return (await response.json()) as HQWorkspaceData;
}

export async function executeHQBusinessAction(
  action: HQBusinessAction,
  item: HQWorkItem,
  csrfToken: string,
  values: Readonly<Record<string, boolean | number | string>>,
): Promise<unknown> {
  const tenantHeaders = item.tenant_id ? { 'X-Tenant-ID': item.tenant_id } : {};
  const response = await fetch(action.path, {
    body: JSON.stringify(values),
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
      ...tenantHeaders,
    },
    method: action.method,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as {
      readonly detail?: string;
      readonly error?: string | Record<string, unknown>;
    } | null;
    const serviceMessage = typeof body?.error === 'string'
      ? body.error
      : body?.detail;
    throw new HQApiError(
      response.status,
      serviceMessage ?? `Action failed with ${response.status}.`,
    );
  }
  return response.status === 204 ? null : response.json();
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

/* ── product master ────────────────────────────────────────────────────────────

   The catalogue layers, each a governed record in its own right: a substance is
   the ingredient, a clinical product is what was prescribed, a manufactured
   product is the brand, and a SKU is the pack that crosses the counter.

   Fields here mirror the serialisers exactly. Anything absent from the response
   is absent from the type, so a section cannot render a field the server never
   sends.
   ────────────────────────────────────────────────────────────────────────────── */

export interface ActiveSubstanceSummary {
  readonly id: string;
  readonly code: string;
  readonly canonical_name: string;
  readonly display_name: string;
  readonly substance_type: string;
  readonly controlled_classification: string;
  readonly status: string;
  /** Reference data shared across tenants rather than owned by one. */
  readonly is_global: boolean;
}

export interface ClinicalProductSummary {
  readonly id: string;
  readonly code: string;
  readonly canonical_name: string;
  readonly dose_form_name: string;
  readonly prescription_classification: string;
  readonly controlled_classification: string;
  readonly antimicrobial_classification: string;
  readonly paediatric_suitable: boolean;
  readonly status: string;
  readonly ingredients: readonly {
    readonly id: string;
    readonly active_substance_name: string;
    readonly numerator_value: string;
    readonly numerator_unit: string;
    readonly role: string;
  }[];
}

export interface ManufacturedProductSummary {
  readonly id: string;
  readonly code: string;
  readonly brand_name: string;
  readonly clinical_product_name: string;
  readonly manufacturer_name: string;
  readonly market_authorisation_number: string;
  readonly licence_status: string;
  readonly status: string;
}

export interface ManufacturerSummary {
  readonly id: string;
  readonly code: string;
  readonly legal_name: string;
  readonly trading_name: string;
  readonly country: string;
  readonly regulator_identifier: string;
  readonly is_active: boolean;
}

export const loadActiveSubstances = (signal?: AbortSignal) =>
  getCollection<ActiveSubstanceSummary>('/api/medicines/substances/', signal);

export const loadClinicalProducts = (signal?: AbortSignal) =>
  getCollection<ClinicalProductSummary>('/api/medicines/clinical-products/', signal);

export const loadManufacturedProducts = (signal?: AbortSignal) =>
  getCollection<ManufacturedProductSummary>(
    '/api/medicines/manufactured-products/',
    signal,
  );

export const loadManufacturers = (signal?: AbortSignal) =>
  getCollection<ManufacturerSummary>('/api/medicines/manufacturers/', signal);

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

/* ────────────────────────────────────────────────────────────────────────────
   Session
   
   A cookie session, not a token. The workspace shows claims, membership numbers
   and cash positions, and a token kept in localStorage is readable by any
   script that reaches the page. The cookie is HttpOnly and this code never sees
   it.
   
   The CSRF token is the one piece the client does hold, and it comes from the
   server on every session read. It is not stored anywhere persistent -- a stale
   token produces a confusing 403 long after the page that fetched it is gone.
   ──────────────────────────────────────────────────────────────────────────── */

export interface SessionUser {
  readonly username: string;
  readonly display_name: string;
  readonly tenant_id: string;
  readonly tenant_name: string;
  readonly is_platform_admin: boolean;
}

export interface SessionState {
  readonly authenticated: boolean;
  readonly csrf_token: string;
  readonly user?: SessionUser;
}

/** Raised when sign-in is refused. Carries the server's own wording. */
export class SignInError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'SignInError';
  }
}

const SESSION_PATH = '/api/identity/session/';

/**
 * Read the current session.
 *
 * Never throws for "not signed in" -- that is an answer, not a failure, and
 * treating it as an error is what turns a sign-in page into a broken page.
 */
export async function readSession(signal?: AbortSignal): Promise<SessionState> {
  const request: RequestInit = {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  };
  if (signal) request.signal = signal;

  const response = await fetch(SESSION_PATH, request);
  if (!response.ok) {
    throw new HQApiError(response.status, `Session read failed with ${response.status}.`);
  }
  return (await response.json()) as SessionState;
}

/**
 * Sign in.
 *
 * The caller passes the CSRF token from a prior session read. The password is
 * passed through and not retained here: it exists in the request body and
 * nowhere else in this module.
 */
export async function signIn(
  username: string,
  password: string,
  csrfToken: string,
): Promise<SessionState> {
  const response = await fetch(SESSION_PATH, {
    method: 'POST',
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
    },
    body: JSON.stringify({ username, password }),
  });

  if (!response.ok) {
    // The server's wording, not ours. It deliberately does not say which of the
    // two fields was wrong, and a client that helpfully guessed would undo
    // that.
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new SignInError(
      response.status,
      body?.detail ??
        (response.status === 429
          ? 'Too many attempts. Wait a moment before trying again.'
          : 'Sign-in failed.'),
    );
  }
  return (await response.json()) as SessionState;
}

/** End the session. */
export async function signOut(csrfToken: string): Promise<void> {
  await fetch(SESSION_PATH, {
    method: 'DELETE',
    credentials: 'include',
    headers: { Accept: 'application/json', 'X-CSRFToken': csrfToken },
  });
}

/* ── claims register ───────────────────────────────────────────────────────── */

export interface ClaimFilters {
  readonly submission_state?: string;
  readonly adjudication_state?: string;
  readonly payment_state?: string;
  readonly insurer?: string;
}

/**
 * The full claims register, filtered.
 *
 * Filters go to the server rather than being applied to a fetched page. A
 * client-side filter over one page of results silently reports "3 rejected
 * claims" when the register holds four hundred, and the number looks
 * authoritative because it was counted rather than guessed.
 */
export function loadClaims(
  filters: ClaimFilters = {},
  signal?: AbortSignal,
): Promise<readonly InsuranceClaim[]> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) query.set(key, value);
  }
  const suffix = query.toString();
  return getCollection<InsuranceClaim>(
    `/api/insurance/claims/${suffix ? `?${suffix}` : ''}`,
    signal,
  );
}

/** The states a claim can be filtered by, for building a filter control. */
export const CLAIM_STATES = {
  submission: [
    'DRAFT',
    'VALIDATING',
    'VALIDATION_FAILED',
    'READY_TO_SUBMIT',
    'SUBMITTED',
    'TRANSPORT_ACCEPTED',
    'TRANSPORT_REJECTED',
  ],
  adjudication: [
    'PENDING',
    'MORE_INFO_REQUIRED',
    'PARTIALLY_APPROVED',
    'APPROVED',
    'REJECTED',
    'REVERSED',
  ],
  payment: ['UNPAID', 'PARTIALLY_PAID', 'PAID'],
} as const;
