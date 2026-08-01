export interface DashboardMetric {
  readonly label: string;
  readonly value: number;
  readonly detail: string;
  readonly accent: string;
  /** HQ hash destination when this metric can be opened. */
  readonly href?: string;
}

let activeTenantContext = '';

export function setHQTenantContext(tenantId: string): void {
  activeTenantContext = tenantId.trim();
}

export function getHQTenantContext(): string {
  return activeTenantContext;
}

function tenantHeaders(tenantId = ''): Record<string, string> {
  const resolvedTenant = tenantId.trim() || activeTenantContext;
  return resolvedTenant ? { 'X-Tenant-ID': resolvedTenant } : {};
}

export interface AttentionItem {
  readonly label: string;
  readonly value: number;
  readonly detail: string;
  readonly tone: string;
  /** HQ hash destination when this signal can be opened. */
  readonly href?: string;
}

export interface DataSummaryItem {
  readonly label: string;
  readonly value: number;
  /** HQ hash destination when this record count can be opened. */
  readonly href?: string;
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

export interface TenantWorkspace extends NetworkItem {
  readonly active_organization_count: number;
  readonly created_at: string;
  readonly metadata: Readonly<Record<string, unknown>>;
  readonly suspension_reason: string;
  readonly updated_at: string;
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

export type HQActionFieldType = 'checkbox' | 'hidden' | 'number' | 'select' | 'text' | 'textarea';

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

export interface HQKnowledgeRelease {
  readonly id: string;
  readonly code: string;
  readonly version: string;
  readonly source: string;
  readonly source_version: string;
  readonly licence: string;
  readonly effective_date: string | null;
  readonly expires_at: string | null;
  readonly is_active: boolean;
  readonly classification: string;
  /** First twelve characters of the SHA-256, enough to compare by eye. */
  readonly checksum: string;
  /** Full SHA-256 digest for particulars / verification. */
  readonly checksum_full?: string;
}

export interface HQCodeSystem {
  readonly id: string;
  readonly name: string;
  readonly title: string;
  readonly url: string;
  readonly version: string;
  readonly content_mode: string;
  readonly is_global: boolean;
  readonly concept_count: number;
  readonly sample_concepts?: readonly { readonly code: string; readonly display: string }[];
}

export interface HQValueSet {
  readonly id: string;
  readonly name: string;
  readonly title: string;
  readonly url: string;
  readonly version: string;
  readonly is_global: boolean;
  readonly compose?: Record<string, unknown>;
}

export interface HQEncounter {
  readonly id: string;
  readonly patient_name: string | null;
  readonly patient_number?: string;
  readonly status: string;
  readonly encounter_class: string;
  readonly practitioner_name: string | null;
  readonly organization_name?: string;
  readonly location_name?: string;
  readonly start_time: string | null;
  readonly end_time: string | null;
  readonly reason_code: string;
}

export interface HQCondition {
  readonly id: string;
  readonly patient_name: string | null;
  readonly clinical_status: string;
  readonly verification_status: string;
  readonly category: string;
  readonly code: string;
  readonly system: string;
  readonly display: string;
  readonly onset_date: string | null;
  readonly recorded_date: string | null;
  readonly encounter_id: string;
}

export interface HQObservation {
  readonly id: string;
  readonly patient_name: string | null;
  readonly status: string;
  readonly category: string;
  readonly code: string;
  readonly system: string;
  readonly display: string;
  readonly effective_time: string | null;
  readonly value_quantity: string;
  readonly value_unit: string;
  readonly value_string: string;
  readonly interpretation: string;
  readonly encounter_id: string;
}

export interface HQFhirIdempotencyRecord {
  readonly id: string;
  readonly key: string;
  readonly resource_type: string;
  readonly operation: string;
  readonly resource_id: string;
  readonly state: string;
  readonly response_status: number | null;
  readonly request_hash: string;
  readonly request_hash_full?: string;
  readonly actor: string;
  readonly created_at: string;
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
  /**
   * Clinical decision support, terminology and encounters.
   *
   * These come through the workspace aggregate rather than /api/cds/,
   * /api/terminology/ and /api/clinical/, because those are capability-gated
   * and filter on the request's tenant -- so a platform administrator, who has
   * no tenant, gets a 403 from them and an empty list past it.
   */
  readonly clinical: {
    readonly counts: {
      readonly encounters: number;
      readonly conditions: number;
      readonly observations: number;
      readonly knowledge_releases: number;
      readonly active_knowledge_releases: number;
      readonly code_systems: number;
      readonly value_sets: number;
      readonly fhir_idempotency_records: number;
      readonly substitutions: number;
      readonly dispensing_labels: number;
    };
    readonly knowledge_releases: readonly HQKnowledgeRelease[];
    readonly code_systems: readonly HQCodeSystem[];
    readonly value_sets: readonly HQValueSet[];
    readonly encounters: readonly HQEncounter[];
    readonly conditions: readonly HQCondition[];
    readonly observations: readonly HQObservation[];
    readonly fhir_idempotency_records: readonly HQFhirIdempotencyRecord[];
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
    headers: { Accept: 'application/json', ...tenantHeaders() },
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
    headers: { Accept: 'application/json', ...tenantHeaders() },
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
  const actionTenantHeaders = tenantHeaders(item.tenant_id);
  const payload = expandActionValues(values);
  const response = await fetch(action.path, {
    body: JSON.stringify(payload),
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
      ...actionTenantHeaders,
    },
    method: action.method,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as unknown;
    const serviceMessage = apiErrorMessage(body);
    throw new HQApiError(
      response.status,
      serviceMessage ?? `Action failed with ${response.status}.`,
    );
  }
  return response.status === 204 ? null : response.json();
}

function apiErrorMessage(value: unknown): string | null {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    const messages = value.map(apiErrorMessage).filter((message): message is string => Boolean(message));
    return messages.length ? messages.join(' ') : null;
  }
  if (!value || typeof value !== 'object') return null;
  const body = value as Record<string, unknown>;
  const primary = apiErrorMessage(body.error) ?? apiErrorMessage(body.detail);
  if (primary) return primary;
  const fields = Object.entries(body)
    .filter(([field]) => field !== 'request_id')
    .map(([field, error]) => {
      const message = apiErrorMessage(error);
      return message ? `${field.replace(/_/g, ' ')}: ${message}` : null;
    })
    .filter((message): message is string => Boolean(message));
  return fields.length ? fields.join(' ') : null;
}

function expandActionValues(
  values: Readonly<Record<string, boolean | number | string>>,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const [name, value] of Object.entries(values)) {
    const separator = name.indexOf('.');
    if (separator === -1) {
      payload[name] = value;
      continue;
    }
    const group = name.slice(0, separator);
    const child = name.slice(separator + 1);
    const nested = (
      typeof payload[group] === 'object'
      && payload[group] !== null
      && !Array.isArray(payload[group])
    ) ? payload[group] as Record<string, unknown> : {};
    nested[child] = value;
    payload[group] = nested;
  }
  return payload;
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
    headers: { Accept: 'application/json', ...tenantHeaders() },
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

async function getTenantCollection<T>(
  path: string,
  tenantId: string,
  signal?: AbortSignal,
): Promise<readonly T[]> {
  const request: RequestInit = {
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...tenantHeaders(tenantId),
    },
  };
  if (signal) request.signal = signal;
  const response = await fetch(path, request);
  if (!response.ok) {
    throw new HQApiError(response.status, `${path} failed with ${response.status}.`);
  }
  return collectionRows<T>(await response.json());
}

async function mutateJson<T>(
  path: string,
  method: 'PATCH' | 'POST',
  payload: unknown,
  csrfToken: string,
  tenantId = '',
): Promise<T> {
  const response = await fetch(path, {
    body: JSON.stringify(payload),
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
      ...tenantHeaders(tenantId),
    },
    method,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as unknown;
    throw new HQApiError(
      response.status,
      apiErrorMessage(body) ?? `${path} failed with ${response.status}.`,
    );
  }
  return (await response.json()) as T;
}

/* ── tenant management ────────────────────────────────────────────────────── */

export interface TenantInput {
  readonly country_code: string;
  readonly metadata?: Readonly<Record<string, unknown>>;
  readonly name: string;
  readonly slug: string;
  readonly time_zone: string;
}

export const loadTenants = (signal?: AbortSignal) =>
  getCollection<TenantWorkspace>('/api/tenancy/tenants/', signal);

/* ── pharmacy network ─────────────────────────────────────────────────────── */

/**
 * A pharmacy's regulatory and commercial record.
 *
 * `licence_is_current` is derived server-side rather than computed here: an
 * expiry is only meaningful against the pharmacy's own date, and the client's
 * clock is not that.
 */
export interface PharmacyProfile {
  readonly legal_name: string;
  readonly business_registration_number: string;
  readonly kra_pin: string;
  readonly ppb_premises_licence_number: string;
  readonly ppb_licence_expiry: string | null;
  readonly superintendent_name: string;
  readonly superintendent_ppb_number: string;
  /**
   * Where the licence data came from. PPB is the registrar; these fields are a
   * copy of its record. Until that integration exists every row is MANUAL.
   */
  readonly licence_source: 'MANUAL' | 'PPB_API';
  readonly licence_last_verified_at: string | null;
  /**
   * Whether the registrar confirmed it, or a person typed it. Deliberately not
   * the same question as `licence_is_current`: a hand-entered licence can be
   * current and wrong at once.
   */
  readonly licence_is_registrar_confirmed: boolean;
  readonly primary_contact_name: string;
  readonly primary_contact_email: string;
  readonly primary_contact_phone: string;
  readonly onboarding_started_at: string | null;
  readonly activated_at: string | null;
  readonly terminated_at: string | null;
  readonly notes: string;
  readonly licence_is_current: boolean;
  readonly days_until_licence_expiry: number | null;
}

export type PharmacyStatus =
  | 'PROSPECT' | 'ONBOARDING' | 'ACTIVE' | 'SUSPENDED' | 'TERMINATED';

export interface Pharmacy {
  readonly id: string;
  readonly name: string;
  readonly slug: string;
  readonly status: PharmacyStatus;
  readonly country_code: string;
  readonly time_zone: string;
  readonly created_at: string;
  readonly profile: PharmacyProfile | null;
  /**
   * What this pharmacy may legitimately do next, decided by the server.
   * The UI renders exactly these, so a button can never offer a transition the
   * service will refuse.
   */
  readonly available_transitions: readonly PharmacyStatus[];
  readonly branch_count: number;
}

export interface PharmacyLifecycleEvent {
  readonly id: string;
  readonly from_state: string;
  readonly to_state: string;
  /** Null means the platform acted, not that nobody is accountable. */
  readonly actor_name: string | null;
  readonly reason: string;
  readonly occurred_at: string;
  readonly context: Readonly<Record<string, unknown>>;
}

export interface PharmacyRegistrationInput {
  readonly name: string;
  readonly slug: string;
  readonly legal_name: string;
  readonly country_code?: string;
  readonly time_zone?: string;
  readonly business_registration_number?: string;
  readonly ppb_premises_licence_number?: string;
  readonly ppb_licence_expiry?: string | null;
  readonly superintendent_name?: string;
  readonly superintendent_ppb_number?: string;
  readonly primary_contact_name?: string;
  readonly primary_contact_email?: string;
  readonly primary_contact_phone?: string;
}

export interface BeginOnboardingInput {
  readonly organization_name: string;
  readonly organization_code: string;
  readonly branch_name: string;
  readonly branch_code: string;
}

const pharmacyPath = (id: string, suffix = '') =>
  `/api/pharmacy-network/pharmacies/${encodeURIComponent(id)}/${suffix}`;

export const loadPharmacies = (signal?: AbortSignal) =>
  getCollection<Pharmacy>('/api/pharmacy-network/pharmacies/', signal);

export const loadPharmacyLifecycle = (id: string, signal?: AbortSignal) =>
  getCollection<PharmacyLifecycleEvent>(pharmacyPath(id, 'lifecycle/'), signal);

/** Registers a PROSPECT. It cannot trade until provisioned and licensed. */
export const registerPharmacy = (
  values: PharmacyRegistrationInput,
  csrfToken: string,
) => mutateJson<Pharmacy>('/api/pharmacy-network/pharmacies/', 'POST', values, csrfToken);

/** Provisions the organization and first branch, and moves to ONBOARDING. */
export const beginPharmacyOnboarding = (
  id: string,
  values: BeginOnboardingInput,
  csrfToken: string,
) => mutateJson<Pharmacy>(pharmacyPath(id, 'begin-onboarding/'), 'POST', values, csrfToken);

/** Refused unless the premises licence is current and a superintendent is named. */
export const activatePharmacy = (id: string, reason: string, csrfToken: string) =>
  mutateJson<Pharmacy>(pharmacyPath(id, 'activate/'), 'POST', { reason }, csrfToken);

export const suspendPharmacy = (id: string, reason: string, csrfToken: string) =>
  mutateJson<Pharmacy>(pharmacyPath(id, 'suspend/'), 'POST', { reason }, csrfToken);

export const reinstatePharmacy = (id: string, reason: string, csrfToken: string) =>
  mutateJson<Pharmacy>(pharmacyPath(id, 'reinstate/'), 'POST', { reason }, csrfToken);

export const terminatePharmacy = (id: string, reason: string, csrfToken: string) =>
  mutateJson<Pharmacy>(pharmacyPath(id, 'terminate/'), 'POST', { reason }, csrfToken);

/** Routine paperwork: recording a renewed licence is not a state change. */
export const updatePharmacyProfile = (
  id: string,
  values: Partial<PharmacyProfile>,
  csrfToken: string,
) => mutateJson<Pharmacy>(pharmacyPath(id, 'profile/'), 'PATCH', values, csrfToken);

/* ── procurement cockpit ──────────────────────────────────────────────────── */

export interface ProcurementSupplier {
  readonly id: string;
  readonly supplier_code: string;
  readonly legal_name: string;
  readonly trading_name: string;
  readonly contact_email: string;
  readonly contact_phone: string;
  readonly payment_terms: string;
  readonly default_currency: string;
  readonly eligibility_reasons: readonly string[];
  readonly purchase_eligible: boolean;
  readonly status: string;
  readonly risk_category: string;
  readonly suspension_reason: string;
}

export interface SupplierQualification {
  readonly id: string;
  readonly supplier: string;
  readonly supplier_code: string;
  readonly qualification_type: string;
  readonly licence_number: string;
  readonly issuing_authority: string;
  readonly effective_date: string;
  readonly expiry_date: string;
  readonly verification_status: string;
}

export interface ProcurementRequisitionLine {
  readonly id: string;
  readonly sku: string;
  readonly sku_code: string;
  readonly requested_quantity: number;
  readonly approved_quantity: number;
  readonly outstanding_quantity: number;
  readonly purchase_unit: string;
  readonly status: string;
}

export interface ProcurementRequisition {
  readonly id: string;
  readonly requisition_number: string;
  readonly requesting_branch: string;
  readonly requesting_branch_name: string;
  readonly requested_delivery_date: string;
  readonly priority: string;
  readonly justification: string;
  readonly status: string;
  readonly lines: readonly ProcurementRequisitionLine[];
  readonly created_at: string;
}

export interface ProcurementOrderLine {
  readonly id: string;
  readonly sku: string;
  readonly sku_code: string;
  readonly ordered_quantity: number;
  readonly received_quantity: number;
  readonly rejected_quantity: number;
  readonly unit_price: Money;
  readonly total_price: Money;
  readonly purchase_unit: string;
  readonly requires_cold_chain: boolean;
}

export interface ProcurementOrder {
  readonly id: string;
  readonly po_number: string;
  readonly supplier: string;
  readonly supplier_name: string;
  readonly originating_requisition: string | null;
  readonly ordering_branch: string;
  readonly order_date: string;
  readonly expected_delivery_date: string;
  readonly currency: string;
  readonly total_gross: Money;
  readonly status: string;
  readonly lines: readonly ProcurementOrderLine[];
}

export interface ProcurementReceiptLine {
  readonly id: string;
  readonly po_line: string;
  readonly sku: string;
  readonly sku_code: string;
  readonly delivered_quantity: number;
  readonly accepted_quantity: number;
  readonly quarantined_quantity: number;
  readonly rejected_quantity: number;
  readonly discrepancy_reason: string;
}

export interface ProcurementReceipt {
  readonly id: string;
  readonly grn_number: string;
  readonly purchase_order: string;
  readonly supplier: string;
  readonly receiving_branch: string;
  readonly delivery_note_number: string;
  readonly arrival_time: string;
  readonly status: string;
  readonly discrepancy_summary: string;
  readonly lines: readonly ProcurementReceiptLine[];
}

export interface ProcurementBatch {
  readonly id: string;
  readonly grn_line: string;
  readonly sku: string;
  readonly sku_code: string;
  readonly manufacturer_batch_number: string;
  readonly manufacture_date: string | null;
  readonly expiry_date: string;
  readonly received_quantity: number;
  readonly accepted_quantity: number;
  readonly quarantined_quantity: number;
  readonly rejected_quantity: number;
  readonly quality_status: string;
  readonly temperature_excursion: boolean;
}

export interface ProcurementInspection {
  readonly id: string;
  readonly goods_receipt: string;
  readonly decision: string;
  readonly reason: string;
  readonly inspected_at: string;
}

export interface ProcurementReturn {
  readonly id: string;
  readonly return_number: string;
  readonly goods_receipt: string;
  readonly supplier: string;
  readonly status: string;
  readonly reason: string;
  readonly lines: readonly {
    readonly id: string;
    readonly sku: string;
    readonly sku_code: string;
    readonly quantity: number;
  }[];
}

export interface ProcurementMatch {
  readonly id: string;
  readonly purchase_order: string;
  readonly goods_receipt: string;
  readonly invoice_reference: string;
  readonly matching_status: string;
  readonly quantity_variance: number;
  readonly price_variance: Money;
}

export interface ProcurementLocation {
  readonly id: string;
  readonly name: string;
  readonly code?: string;
  readonly branch?: string;
  readonly location_type: string;
  readonly status: string;
  readonly quarantine_capability?: boolean;
}

export interface ProcurementSku {
  readonly id: string;
  readonly sku_code: string;
  readonly display_name: string;
  readonly status: string;
}

export interface ProcurementData {
  readonly batches: readonly ProcurementBatch[];
  readonly inspections: readonly ProcurementInspection[];
  readonly inventoryLocations: readonly ProcurementLocation[];
  readonly locations: readonly ProcurementLocation[];
  readonly matches: readonly ProcurementMatch[];
  readonly orders: readonly ProcurementOrder[];
  readonly qualifications: readonly SupplierQualification[];
  readonly receipts: readonly ProcurementReceipt[];
  readonly requisitions: readonly ProcurementRequisition[];
  readonly returns: readonly ProcurementReturn[];
  readonly skus: readonly ProcurementSku[];
  readonly suppliers: readonly ProcurementSupplier[];
}

interface ProcurementContext {
  readonly inventory_locations: readonly ProcurementLocation[];
  readonly locations: readonly ProcurementLocation[];
  readonly skus: readonly ProcurementSku[];
}

async function loadProcurementContext(
  tenantId: string,
  signal?: AbortSignal,
): Promise<ProcurementContext> {
  const request: RequestInit = {
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      'X-Tenant-ID': tenantId,
    },
  };
  if (signal) request.signal = signal;
  const response = await fetch('/api/procurement/context/', request);
  if (!response.ok) {
    throw new HQApiError(response.status, `Procurement context failed with ${response.status}.`);
  }
  return (await response.json()) as ProcurementContext;
}

export async function loadProcurementData(
  tenantId: string,
  signal?: AbortSignal,
): Promise<ProcurementData> {
  const [
    suppliers,
    qualifications,
    requisitions,
    orders,
    receipts,
    batches,
    inspections,
    returns,
    matches,
    context,
  ] = await Promise.all([
    getTenantCollection<ProcurementSupplier>('/api/procurement/suppliers/', tenantId, signal),
    getTenantCollection<SupplierQualification>('/api/procurement/supplier-qualifications/', tenantId, signal),
    getTenantCollection<ProcurementRequisition>('/api/procurement/requisitions/', tenantId, signal),
    getTenantCollection<ProcurementOrder>('/api/procurement/purchase-orders/', tenantId, signal),
    getTenantCollection<ProcurementReceipt>('/api/procurement/goods-receipts/', tenantId, signal),
    getTenantCollection<ProcurementBatch>('/api/procurement/received-batches/', tenantId, signal),
    getTenantCollection<ProcurementInspection>('/api/procurement/inspections/', tenantId, signal),
    getTenantCollection<ProcurementReturn>('/api/procurement/supplier-returns/', tenantId, signal),
    getTenantCollection<ProcurementMatch>('/api/procurement/matching/', tenantId, signal),
    loadProcurementContext(tenantId, signal),
  ]);
  return {
    batches,
    inspections,
    inventoryLocations: context.inventory_locations,
    locations: context.locations,
    matches,
    orders,
    qualifications,
    receipts,
    requisitions,
    returns,
    skus: context.skus,
    suppliers,
  };
}

export const procurementCommand = <T>(
  path: string,
  payload: unknown,
  tenantId: string,
  csrfToken: string,
) => mutateJson<T>(path, 'POST', payload, csrfToken, tenantId);

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

export const loadInsurers = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<Insurer>('/api/insurance/insurers/', tenantId, signal);

export interface CreateInsurerInput {
  readonly code: string;
  readonly name: string;
  readonly insurer_type?: string | undefined;
  readonly integration_adapter: string;
  readonly environment: string;
  readonly status?: string | undefined;
}

export const createInsurer = (
  input: CreateInsurerInput,
  csrfToken: string,
  tenantId = '',
): Promise<Insurer> =>
  mutateJson<Insurer>('/api/insurance/insurers/', 'POST', input, csrfToken, tenantId);

/** Claims the insurer agreed to pay and has not paid. The money owed. */
export const loadApprovedUnpaidClaims = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<InsuranceClaim>('/api/insurance/claims/approved-unpaid/', tenantId, signal);

/**
 * Sent, acknowledged, still undecided.
 *
 * Deliberately a separate call from approved-unpaid: one is chased with the
 * insurer, the other is chased for payment, and showing them together is how
 * transport acceptance starts looking like a debt.
 */
export const loadClaimsAwaitingDecision = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<InsuranceClaim>('/api/insurance/claims/awaiting-decision/', tenantId, signal);

/** Everything blocked on this end rather than on the insurer. */
export const loadClaimsNeedingAttention = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<InsuranceClaim>('/api/insurance/claims/needs-attention/', tenantId, signal);

export interface InsuranceRemittance {
  readonly id: string;
  readonly remittance_number: string;
  readonly insurer_code: string;
  readonly total_remitted_amount: string;
  readonly payment_reference: string;
  readonly remittance_date: string;
  readonly status: string;
  readonly unmatched_lines: number;
}

export interface ClaimRejection {
  readonly id: string;
  readonly claim_number: string;
  readonly rejection_code: string;
  readonly reason_description: string;
  readonly resubmission_eligible: boolean;
  readonly operator_action: string;
  readonly resolved: boolean;
  readonly created_at: string;
}

export interface InsuranceCoverage {
  readonly id: string;
  readonly membership_number: string;
  readonly relationship: string;
  readonly valid_from: string;
  readonly valid_to: string;
  readonly status: string;
  readonly remaining_limit: string;
  readonly copay_amount: string;
  readonly coinsurance_percentage: string;
}

export const loadRemittances = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<InsuranceRemittance>('/api/insurance/remittances/', tenantId, signal);

export const loadRejections = (tenantId: string, unresolvedOnly = true, signal?: AbortSignal) =>
  getTenantCollection<ClaimRejection>(
    unresolvedOnly ? '/api/insurance/rejections/?unresolved=true' : '/api/insurance/rejections/',
    tenantId,
    signal,
  );

export const loadCoverages = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<InsuranceCoverage>('/api/insurance/coverages/', tenantId, signal);

/* ── tenancy & counterparty customers ─────────────────────────────────────── */

export interface TenantItem {
  readonly id: string;
  readonly name: string;
  readonly slug: string;
  readonly status: string;
  readonly country_code: string;
  readonly time_zone: string;
  readonly suspension_reason: string;
  readonly active_location_count: number;
  readonly active_organization_count: number;
  readonly active_patient_count: number;
  readonly active_practitioner_count: number;
  readonly active_user_count: number;
  readonly created_at: string;
}

export interface CustomerItem {
  readonly id: string;
  readonly customer_number: string;
  readonly legal_name: string;
  readonly trading_name: string;
  readonly customer_type: string;
  readonly registration_number: string;
  readonly tax_number: string;
  readonly contact_email: string;
  readonly contact_phone: string;
  readonly status: string;
  readonly risk_classification: string;
  readonly credit_status: string;
  readonly default_currency: string;
  readonly payment_terms: string;
  readonly controlled_medicine_eligible: boolean;
  readonly cold_chain_capable: boolean;
  readonly created_at: string;
}

export const loadCustomers = (signal?: AbortSignal) =>
  getCollection<CustomerItem>('/api/customers/customers/', signal);

export interface CreateCustomerInput {
  readonly customer_number: string;
  readonly legal_name: string;
  readonly trading_name?: string | undefined;
  readonly customer_type: string;
  readonly registration_number?: string | undefined;
  readonly tax_number?: string | undefined;
  readonly contact_email?: string | undefined;
  readonly contact_phone?: string | undefined;
  readonly risk_classification?: string | undefined;
  readonly controlled_medicine_eligible?: boolean | undefined;
  readonly cold_chain_capable?: boolean | undefined;
}

export const createCustomer = (
  input: CreateCustomerInput,
  csrfToken: string,
): Promise<CustomerItem> =>
  mutateJson<CustomerItem>('/api/customers/customers/', 'POST', input, csrfToken);

export const approveCustomer = (
  id: string,
  reason: string,
  csrfToken: string,
) => mutateJson<{ readonly status: string }>(
  `/api/customers/customers/${encodeURIComponent(id)}/approve/`,
  'POST',
  { reason },
  csrfToken,
);

export const beginCustomerReview = (
  id: string,
  reason: string,
  csrfToken: string,
) => mutateJson<{ readonly status: string }>(
  `/api/customers/customers/${encodeURIComponent(id)}/begin-review/`,
  'POST',
  { reason },
  csrfToken,
);

export const activateCustomer = (
  id: string,
  reason: string,
  csrfToken: string,
) => mutateJson<{ readonly status: string }>(
  `/api/customers/customers/${encodeURIComponent(id)}/activate/`,
  'POST',
  { reason },
  csrfToken,
);

export const suspendCustomer = (
  id: string,
  reason: string,
  csrfToken: string,
) => mutateJson<{ readonly status: string }>(
  `/api/customers/customers/${encodeURIComponent(id)}/suspend/`,
  'POST',
  { reason },
  csrfToken,
);

export const reactivateCustomer = (
  id: string,
  reason: string,
  csrfToken: string,
) => mutateJson<{ readonly status: string }>(
  `/api/customers/customers/${encodeURIComponent(id)}/reactivate/`,
  'POST',
  { reason },
  csrfToken,
);

/* ── till & cash custody control ───────────────────────────────────────────── */

export interface PosRegisterItem {
  readonly id: string;
  readonly code: string;
  readonly name: string;
  readonly device_id: string;
  readonly state: string;
  readonly expected_float: string;
  readonly currency: string;
  readonly last_synchronised_at: string | null;
}

export interface CashMovementItem {
  readonly id: string;
  readonly register_session_id: string;
  readonly register_code: string;
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

export interface CashDeclarationItem {
  readonly id: string;
  readonly register_session_id: string;
  readonly register_code: string;
  readonly kind: string;
  readonly declared_amount: string;
  readonly currency: string;
  readonly attempt: number;
  readonly declared_by_username: string;
  readonly confirmed_at: string | null;
  readonly is_confirmed: boolean;
  readonly reason: string;
}

export interface BusinessDayItem {
  readonly id: string;
  readonly business_date: string;
  readonly state: string;
  readonly opened_at: string;
  readonly closed_at: string | null;
  readonly reopen_reason: string;
}

export const loadPosRegisters = (tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<PosRegisterItem>('/api/pos/shift/registers/', tenantId, signal);

export interface PosDeviceHealthItem {
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
  readonly last_heartbeat: string;
}

export const loadPosDeviceHealth = (signal?: AbortSignal) =>
  getCollection<PosDeviceHealthItem>('/api/pos/dispensing/devices/', signal);

export const loadCashMovements = (tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<CashMovementItem>('/api/pos/shift/cash-movements/', tenantId, signal);

export const loadCashDeclarations = (tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<CashDeclarationItem>('/api/pos/shift/cash-declarations/', tenantId, signal);

export const loadBusinessDays = (tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<BusinessDayItem>('/api/pos/shift/business-days/', tenantId, signal);

export const approveCashMovement = (
  movementId: string,
  csrfToken: string,
) => mutateJson<CashMovementItem>(
  `/api/pos/shift/cash-movements/${encodeURIComponent(movementId)}/approve/`,
  'POST',
  {},
  csrfToken,
);

/* ── pricing ───────────────────────────────────────────────────────────────── */

export interface PriceBookSummary {
  readonly id: string;
  readonly code: string;
  readonly name: string;
  readonly currency: string;
  readonly price_type: string;
  readonly scope_type: string;
  readonly priority: number;
  readonly tax_inclusive: boolean;
  readonly is_active: boolean;
  /** Null when the book is configured but has nothing a till could charge. */
  readonly live_version: number | null;
}

export interface PriceBookVersion {
  readonly id: string;
  readonly price_book_code: string;
  readonly version_number: number;
  readonly status: string;
  readonly is_published: boolean;
  readonly effective_from: string;
  readonly effective_to: string | null;
  readonly approved_at: string | null;
  readonly published_at: string | null;
  readonly entry_count: number;
}

export interface PriceBookEntry {
  readonly id: string;
  readonly sku_code: string;
  readonly version_number: number;
  readonly unit_price: Money;
  readonly minimum_quantity: string;
  readonly maximum_quantity: string | null;
  readonly minimum_allowed_price: Money | null;
  readonly tax_inclusive: boolean;
}

export interface PriceAssignment {
  readonly id: string;
  readonly price_book_code: string;
  readonly scope_type: string;
  readonly branch: string | null;
  readonly branch_code: string | null;
  readonly branch_name: string | null;
  readonly branch_group: string;
  readonly region: string;
  readonly customer_segment: string;
  readonly priority: number;
  readonly valid_from: string | null;
  readonly valid_to: string | null;
  readonly is_active: boolean;
}

export interface AppliedPriceSnapshot {
  readonly id: string;
  readonly line_reference: string;
  readonly line_type: string;
  readonly sku_code: string;
  readonly quantity: string;
  readonly currency: string;
  readonly unit_price: Money;
  readonly line_total: Money;
  readonly discount_amount: Money;
  readonly tax_amount: Money;
  readonly source: string;
  readonly source_reference: string;
  readonly resolution_trace: readonly string[];
  readonly context_hash: string;
  readonly resolved_at: string;
}

export interface ManualPriceOverride {
  readonly id: string;
  readonly sku_code: string;
  readonly transaction_reference: string;
  readonly resolved_price: Money;
  readonly override_price: Money;
  readonly difference: string;
  readonly reason_code: string;
  readonly reason: string;
  readonly status: string;
  readonly requested_by_username: string;
  readonly approved_by_username: string;
  readonly approved_at: string | null;
  readonly expires_at: string | null;
  readonly created_at: string;
}

export interface PriceLock {
  readonly id: string;
  readonly basket_reference: string;
  readonly line_reference: string;
  readonly sku_code: string;
  readonly locked_unit_price: Money;
  readonly quantity: string;
  readonly currency: string;
  readonly source: string;
  readonly locked_at: string;
  readonly expires_at: string;
  readonly status: string;
  readonly is_live: boolean;
  readonly invalidation_reason: string;
}

export interface PriceResolutionResult {
  readonly unit_price: Money;
  readonly currency: string;
  readonly source: string;
  readonly source_reference: string;
  readonly tax_inclusive: boolean;
  readonly explanation: string;
  readonly considered: readonly string[];
  readonly context_hash: string;
}

export interface PriceDraftResult {
  readonly status: 'DRAFT';
  readonly sku_code: string;
  readonly unit_price: Money;
  readonly minimum_allowed_price: Money | null;
  readonly tax_inclusive: boolean;
  readonly price_book: string;
  readonly version_id: string;
  readonly version_number: number;
  readonly created: boolean;
}

export const loadPriceBooks = (tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<PriceBookSummary>('/api/pricing/books/', tenantId, signal);

export const loadPriceBookVersions = (bookId = '', tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<PriceBookVersion>(
    bookId ? `/api/pricing/versions/?price_book=${encodeURIComponent(bookId)}` : '/api/pricing/versions/',
    tenantId,
    signal,
  );

export const loadPriceBookEntries = (versionId = '', tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<PriceBookEntry>(
    versionId ? `/api/pricing/entries/?version=${encodeURIComponent(versionId)}` : '/api/pricing/entries/',
    tenantId,
    signal,
  );

export const loadPriceAssignments = (tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<PriceAssignment>('/api/pricing/assignments/', tenantId, signal);

export const loadAppliedPrices = (tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<AppliedPriceSnapshot>('/api/pricing/applied/', tenantId, signal);

export const loadPriceOverrides = (pendingOnly = false, tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<ManualPriceOverride>(
    pendingOnly ? '/api/pricing/overrides/?pending=true' : '/api/pricing/overrides/',
    tenantId,
    signal,
  );

export const loadPriceLocks = (tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<PriceLock>('/api/pricing/locks/', tenantId, signal);

export const loadTenantSkus = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<HQSku>('/api/medicines/skus/?page_size=100', tenantId, signal);

export const saveTenantPriceDraft = (
  payload: {
    readonly sku_code: string;
    readonly unit_price: Money;
    readonly minimum_allowed_price: Money | null;
    readonly tax_inclusive: boolean;
  },
  tenantId: string,
  csrfToken: string,
) => mutateJson<PriceDraftResult>(
  '/api/pricing/prices/set-price/',
  'POST',
  payload,
  csrfToken,
  tenantId,
);

export const transitionPriceBookVersion = (
  versionId: string,
  action: 'approve' | 'publish' | 'submit',
  csrfToken: string,
) => mutateJson<PriceBookVersion>(
  `/api/pricing/versions/${encodeURIComponent(versionId)}/${action}/`,
  'POST',
  {},
  csrfToken,
);

export const decidePriceOverride = (
  overrideId: string,
  decision: 'approve' | 'reject',
  csrfToken: string,
  reason = '',
) => mutateJson<ManualPriceOverride>(
  `/api/pricing/overrides/${encodeURIComponent(overrideId)}/${decision}/`,
  'POST',
  decision === 'reject' ? { reason } : {},
  csrfToken,
);

export async function resolvePrice(
  params: {
    readonly branch?: string;
    readonly sku?: string;
    readonly quantity?: string;
    readonly service_date?: string;
    readonly currency?: string;
  },
  signal?: AbortSignal,
): Promise<PriceResolutionResult> {
  const searchParams = new URLSearchParams();
  if (params.branch) searchParams.set('branch', params.branch);
  if (params.sku) searchParams.set('sku', params.sku);
  if (params.quantity) searchParams.set('quantity', params.quantity);
  if (params.service_date) searchParams.set('service_date', params.service_date);
  if (params.currency) searchParams.set('currency', params.currency);

  const request: RequestInit = {
    credentials: 'include',
    headers: { Accept: 'application/json', ...tenantHeaders() },
  };
  if (signal) request.signal = signal;

  const response = await fetch(`/api/pricing/prices/resolve/?${searchParams.toString()}`, request);
  if (!response.ok) {
    const errorJson = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new HQApiError(response.status, errorJson.detail || `Price resolution failed with status ${response.status}.`);
  }
  return (await response.json()) as PriceResolutionResult;
}

/* ── identity & access control ─────────────────────────────────────────────── */

export interface RoleDetail {
  readonly id: string;
  readonly code: string;
  readonly name: string;
  readonly capabilities: readonly string[];
  readonly is_active: boolean;
  readonly is_system: boolean;
  readonly user_count: number;
}

export interface UserDetail {
  readonly id: string;
  readonly username: string;
  readonly email: string;
  readonly first_name: string;
  readonly last_name: string;
  readonly is_active: boolean;
  readonly account_status: 'ACTIVE' | 'SUSPENDED' | 'DISABLED' | string;
  readonly category: string;
  readonly is_platform_admin: boolean;
  readonly is_superuser: boolean;
  readonly must_change_password: boolean;
  readonly professional_staff_id: string;
  readonly assigned_roles: readonly { readonly id: string; readonly code: string; readonly name: string }[];
  readonly effective_capabilities: readonly string[];
  readonly date_joined: string;
  readonly last_login: string | null;
  readonly temporary_password?: string;
}

export interface UserRoleGrant {
  readonly id: string;
  readonly user: string;
  readonly user_username: string;
  readonly role: string;
  readonly role_code: string;
  readonly role_name: string;
  readonly is_active: boolean;
  readonly created_at: string;
}

export interface ServiceAccountItem {
  readonly id: string;
  readonly code: string;
  readonly display_name: string;
  readonly capabilities: readonly string[];
  readonly is_active: boolean;
  readonly credential_fingerprint: string;
  readonly created_at: string;
}

export interface CapabilityCatalogue {
  readonly capabilities: readonly string[];
  readonly groups: readonly {
    readonly label: string;
    readonly capabilities: readonly string[];
  }[];
}

export interface CapabilityMatrixData {
  readonly tenant_id: string;
  readonly catalogue?: CapabilityCatalogue;
  readonly roles: readonly {
    readonly id: string;
    readonly code: string;
    readonly name: string;
    readonly capabilities: readonly string[];
    readonly is_system: boolean;
    readonly assigned_users_count: number;
  }[];
  readonly users: readonly {
    readonly id: string;
    readonly username: string;
    readonly email: string;
    readonly is_platform_admin: boolean;
    readonly is_superuser: boolean;
    readonly assigned_roles: readonly string[];
    readonly effective_capabilities: readonly string[];
  }[];
  readonly service_accounts: readonly {
    readonly id: string;
    readonly code: string;
    readonly display_name: string;
    readonly capabilities: readonly string[];
    readonly fingerprint: string;
  }[];
}

export interface UserDirectoryPage {
  readonly count: number;
  readonly next: string | null;
  readonly previous: string | null;
  readonly results: readonly UserDetail[];
}

export interface UserDirectoryFilters {
  readonly search?: string;
  readonly category?: string;
  readonly page?: number;
  readonly pageSize?: number;
}

export const loadRolesDetail = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<RoleDetail>('/api/identity/roles-detail/', tenantId, signal);

export const loadUsers = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<UserDetail>('/api/identity/users/?page_size=100', tenantId, signal);

export async function loadUserDirectory(
  tenantId: string,
  filters: UserDirectoryFilters = {},
  signal?: AbortSignal,
): Promise<UserDirectoryPage> {
  const parameters = new URLSearchParams();
  parameters.set('page_size', String(filters.pageSize ?? 20));
  parameters.set('page', String(filters.page ?? 1));
  if (filters.search?.trim()) parameters.set('search', filters.search.trim());
  if (filters.category?.trim()) parameters.set('category', filters.category.trim());
  const request: RequestInit = {
    credentials: 'include',
    headers: { Accept: 'application/json', ...tenantHeaders(tenantId) },
  };
  if (signal) request.signal = signal;
  const response = await fetch(`/api/identity/users/?${parameters.toString()}`, request);
  if (!response.ok) {
    throw new HQApiError(response.status, `User directory failed with ${response.status}.`);
  }
  const body = await response.json();
  if (Array.isArray(body)) {
    return { count: body.length, next: null, previous: null, results: body as UserDetail[] };
  }
  return body as UserDirectoryPage;
}

export async function createTenantUser(
  tenantId: string,
  csrfToken: string,
  payload: {
    readonly username: string;
    readonly email?: string;
    readonly first_name?: string;
    readonly last_name?: string;
    readonly password?: string;
    readonly professional_staff_id?: string;
    readonly role_ids?: readonly string[];
    readonly must_change_password?: boolean;
  },
): Promise<UserDetail> {
  return mutateJson<UserDetail>('/api/identity/users/', 'POST', payload, csrfToken, tenantId);
}

export async function setUserAccountStatus(
  tenantId: string,
  userId: string,
  action: 'activate' | 'suspend' | 'disable',
  csrfToken: string,
): Promise<UserDetail> {
  return mutateJson<UserDetail>(
    `/api/identity/users/${userId}/${action}/`,
    'POST',
    {},
    csrfToken,
    tenantId,
  );
}

export async function resetUserPassword(
  tenantId: string,
  userId: string,
  csrfToken: string,
  password?: string,
): Promise<UserDetail> {
  return mutateJson<UserDetail>(
    `/api/identity/users/${userId}/reset-password/`,
    'POST',
    password ? { password } : {},
    csrfToken,
    tenantId,
  );
}

export async function setUserRoles(
  tenantId: string,
  userId: string,
  roleIds: readonly string[],
  csrfToken: string,
): Promise<UserDetail> {
  return mutateJson<UserDetail>(
    `/api/identity/users/${userId}/set-roles/`,
    'POST',
    { role_ids: roleIds },
    csrfToken,
    tenantId,
  );
}

export async function createTenantRole(
  tenantId: string,
  csrfToken: string,
  payload: {
    readonly code: string;
    readonly name: string;
    readonly capabilities?: readonly string[];
    readonly is_active?: boolean;
  },
): Promise<RoleDetail> {
  return mutateJson<RoleDetail>('/api/identity/roles-detail/', 'POST', payload, csrfToken, tenantId);
}

export async function updateRolePermissions(
  tenantId: string,
  roleId: string,
  csrfToken: string,
  payload: {
    readonly name?: string;
    readonly capabilities?: readonly string[];
    readonly is_active?: boolean;
  },
): Promise<RoleDetail> {
  return mutateJson<RoleDetail>(
    `/api/identity/roles-detail/${roleId}/`,
    'PATCH',
    payload,
    csrfToken,
    tenantId,
  );
}

export const loadUserRoles = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<UserRoleGrant>('/api/identity/user-roles/', tenantId, signal);

export const loadServiceAccounts = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<ServiceAccountItem>('/api/identity/service-accounts/', tenantId, signal);

export async function loadCapabilityMatrix(
  tenantId: string,
  signal?: AbortSignal,
): Promise<CapabilityMatrixData> {
  const request: RequestInit = {
    credentials: 'include',
    headers: { Accept: 'application/json', ...tenantHeaders(tenantId) },
  };
  if (signal) request.signal = signal;

  const response = await fetch('/api/identity/matrix/', request);
  if (!response.ok) {
    throw new HQApiError(response.status, `Capability matrix request failed with ${response.status}.`);
  }
  return (await response.json()) as CapabilityMatrixData;
}

/* ── enterprise reporting ──────────────────────────────────────────────────── */

export type ReportExportFormat = 'pdf' | 'csv' | 'json' | 'xlsx';
export type ReportGranularity = 'HOURLY' | 'DAILY' | 'WEEKLY' | 'MONTHLY' | 'YEARLY';

export interface ReportDownloadReceipt {
  readonly receiptId: string;
  readonly validationCode: string;
  readonly checksumSha256: string;
  readonly validationUrl: string;
  readonly filename: string;
}

function terminalFingerprint(): { terminalId: string; terminalLabel: string } {
  const existing = window.sessionStorage.getItem('tibatrace.hq.terminal_id');
  const terminalId = existing || (() => {
    const id = (globalThis.crypto?.randomUUID?.() || `hq-${Date.now()}`).slice(0, 36);
    window.sessionStorage.setItem('tibatrace.hq.terminal_id', id);
    return id;
  })();
  return {
    terminalId,
    terminalLabel: `HQ Web · ${window.location.host}`,
  };
}

export interface ReportFilterOptions {
  readonly fromIso?: string;
  readonly toIso?: string;
  readonly granularity?: ReportGranularity;
}

export async function downloadEnterpriseReport(
  reportId: string,
  format: ReportExportFormat,
  csrfToken: string,
  tenantId = '',
  filterOptions?: ReportFilterOptions,
): Promise<ReportDownloadReceipt> {
  const terminal = terminalFingerprint();
  const queryParams = new URLSearchParams();
  if (filterOptions?.fromIso) queryParams.set('from_iso', filterOptions.fromIso);
  if (filterOptions?.toIso) queryParams.set('to_iso', filterOptions.toIso);
  if (filterOptions?.granularity) queryParams.set('granularity', filterOptions.granularity);
  const queryString = queryParams.toString() ? `?${queryParams.toString()}` : '';

  const response = await fetch(`/api/hq/reports/${encodeURIComponent(reportId)}/download/${queryString}`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      Accept: '*/*',
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
      'X-Terminal-ID': terminal.terminalId,
      'X-Terminal-Label': terminal.terminalLabel,
      ...tenantHeaders(tenantId),
    },
    body: JSON.stringify({
      format,
      terminal_id: terminal.terminalId,
      terminal_label: terminal.terminalLabel,
      start_date_time: filterOptions?.fromIso || null,
      end_date_time: filterOptions?.toIso || null,
      granularity: filterOptions?.granularity || null,
    }),
  });
  if (!response.ok) {
    const errorJson = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new HQApiError(response.status, errorJson.detail || `Report download failed with ${response.status}.`);
  }
  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const matched = /filename="([^"]+)"/i.exec(disposition);
  const filename = matched?.[1] || `${reportId}.${format === 'xlsx' ? 'csv' : format}`;
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
  return {
    receiptId: response.headers.get('X-Report-Receipt-Id') || '',
    validationCode: response.headers.get('X-Report-Validation-Code') || '',
    checksumSha256: response.headers.get('X-Report-Checksum-SHA256') || '',
    validationUrl: response.headers.get('X-Report-Validation-Url') || '',
    filename,
  };
}

export async function validateReportReceipt(
  receiptId: string,
  tenantId = '',
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  const request: RequestInit = {
    credentials: 'include',
    headers: { Accept: 'application/json', ...tenantHeaders(tenantId) },
  };
  if (signal) request.signal = signal;
  const response = await fetch(`/api/hq/reports/validate/${encodeURIComponent(receiptId)}/`, request);
  if (!response.ok) {
    throw new HQApiError(response.status, `Report validation failed with ${response.status}.`);
  }
  return (await response.json()) as Record<string, unknown>;
}

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

export interface GovernmentCatalogueMedicine {
  readonly id: string;
  readonly code: string;
  readonly generic_name: string;
  readonly brand_name: string;
  readonly dosage_form: string;
  readonly strength: string;
  readonly route: string;
  readonly licence_identifier: string;
  readonly manufacturer_name: string;
  readonly keml_status: string;
  readonly level_of_use: string;
  readonly status: string;
  readonly catalogue_standard: string;
  readonly source_updated_at: string;
  readonly selected: boolean;
  readonly selection_status: string;
  readonly tenant_code: string;
}

export interface GovernmentCatalogueFilters {
  readonly kemlStatus?: string;
  readonly levelOfUse?: string;
  readonly page?: number;
  readonly pageSize?: number;
  readonly query?: string;
  readonly selectedOnly?: boolean;
  readonly tenantId?: string;
}

export interface GovernmentCataloguePage {
  readonly available_keml_statuses: readonly string[];
  readonly available_levels_of_use: readonly string[];
  readonly catalogue_count: number;
  readonly count: number;
  readonly page: number;
  readonly page_size: number;
  readonly pages: number;
  readonly results: readonly GovernmentCatalogueMedicine[];
  readonly selected_count: number;
  readonly source: string;
  readonly source_version: string;
  readonly tenant_id: string;
  readonly tenant_name: string;
  readonly can_manage: boolean;
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

export async function loadGovernmentCatalogue(
  filters: GovernmentCatalogueFilters = {},
  signal?: AbortSignal,
): Promise<GovernmentCataloguePage> {
  const parameters = new URLSearchParams();
  if (filters.query?.trim()) parameters.set('q', filters.query.trim());
  if (filters.kemlStatus) parameters.set('keml_status', filters.kemlStatus);
  if (filters.levelOfUse) parameters.set('level_of_use', filters.levelOfUse);
  if (filters.selectedOnly) parameters.set('selected_only', 'true');
  if (filters.page) parameters.set('page', String(filters.page));
  if (filters.pageSize) parameters.set('page_size', String(filters.pageSize));

  const request: RequestInit = {
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...tenantHeaders(filters.tenantId),
    },
  };
  if (signal) request.signal = signal;
  const query = parameters.toString();
  const path = `/api/medicines/government-catalogue/${query ? `?${query}` : ''}`;
  const response = await fetch(path, request);
  if (!response.ok) {
    throw new HQApiError(response.status, `Government catalogue request failed with ${response.status}.`);
  }
  return (await response.json()) as GovernmentCataloguePage;
}

export async function updateGovernmentCatalogueSelection(
  medicineId: string,
  selected: boolean,
  tenantId: string,
  csrfToken: string,
): Promise<{ readonly selected: boolean }> {
  const response = await fetch(
    `/api/medicines/government-catalogue/${encodeURIComponent(medicineId)}/selection/`,
    {
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        'X-CSRFToken': csrfToken,
        'X-Tenant-ID': tenantId,
      },
      method: selected ? 'POST' : 'DELETE',
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null) as unknown;
    throw new HQApiError(
      response.status,
      apiErrorMessage(body) ?? `Catalogue selection failed with ${response.status}.`,
    );
  }
  return (await response.json()) as { readonly selected: boolean };
}

/* ── system health ─────────────────────────────────────────────────────────── */

export type SystemHealth = 'checking' | 'live' | 'degraded' | 'unreachable';

export interface EndpointHeartbeat {
  readonly checkedAt: string;
  readonly endpoint: string;
  readonly latencyMs: number;
  readonly status: 'ONLINE' | 'DEGRADED' | 'OFFLINE';
  readonly statusCode: number | null;
}

export async function probeEndpointHeartbeat(
  endpoint: string,
  signal?: AbortSignal,
): Promise<EndpointHeartbeat> {
  const startedAt = Date.now();
  const request: RequestInit = {
    credentials: 'include',
    headers: { Accept: 'application/json', ...tenantHeaders() },
  };
  if (signal) request.signal = signal;

  try {
    const response = await fetch(endpoint, request);
    return {
      checkedAt: new Date().toISOString(),
      endpoint,
      latencyMs: Math.max(Date.now() - startedAt, 0),
      status: response.ok ? 'ONLINE' : 'DEGRADED',
      statusCode: response.status,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    return {
      checkedAt: new Date().toISOString(),
      endpoint,
      latencyMs: Math.max(Date.now() - startedAt, 0),
      status: 'OFFLINE',
      statusCode: null,
    };
  }
}

/**
 * Ask the backend whether it is well.
 *
 * The topbar indicator used to be the literal text "System live" beside a green
 * dot, linking to the raw health JSON. Nothing checked anything, so it read
 * "System live" whatever the state of the system -- the same shape of claim as
 * a screening banner that says PASSED without a screening.
 */
export async function loadSystemHealth(signal?: AbortSignal): Promise<SystemHealth> {
  const request: RequestInit = { credentials: 'include', headers: { Accept: 'application/json' } };
  if (signal) request.signal = signal;
  let response: Response;
  try {
    response = await fetch('/api/health/', request);
  } catch {
    // Nothing answered. Aborted requests land here too; the caller discards
    // those because it only applies a result while still mounted.
    return 'unreachable';
  }

  if (!response.ok) return 'degraded';

  try {
    const body = (await response.json()) as { status?: string };
    // Anything other than an explicit ok is degraded. Absence of a reported
    // problem is not the same as a reported healthy state.
    return body.status === 'ok' ? 'live' : 'degraded';
  } catch {
    // It answered, and the answer was not readable. That is a sick backend, not
    // an absent one -- reporting "unreachable" would send somebody to check the
    // network instead of the server.
    return 'degraded';
  }
}

/* ── POS installers ───────────────────────────────────────────────────────── */

export interface PosRelease {
  readonly id: string;
  readonly platform: 'ANDROID' | 'WINDOWS';
  readonly version: string;
  readonly build_number: number;
  readonly size_bytes: number;
  /** Published so an operator can verify the download before installing. */
  readonly sha256: string;
  readonly release_notes: string;
  readonly minimum_os: string;
  readonly minimum_supported_build: number;
  readonly operations_impact: string;
  readonly published_at: string | null;
  readonly download_filename: string;
}

export interface PosReleaseCatalogue {
  /** False when object storage is not configured; links are disabled, not broken. */
  readonly downloads_available: boolean;
  readonly url_ttl_seconds: number;
  readonly storage_backend: 'local' | 's3';
  readonly releases: readonly PosRelease[];
}

export async function loadPosReleases(signal?: AbortSignal): Promise<PosReleaseCatalogue> {
  const request: RequestInit = { credentials: 'include', headers: { Accept: 'application/json' } };
  if (signal) request.signal = signal;
  const response = await fetch('/api/hq/pos-releases/', request);
  if (!response.ok) {
    throw new HQApiError(response.status, `POS release list failed with ${response.status}.`);
  }
  return (await response.json()) as PosReleaseCatalogue;
}

export interface PosDownloadGrant {
  readonly url: string;
  readonly filename: string;
  readonly expires_in_seconds: number;
  readonly sha256: string;
  readonly size_bytes: number;
}

/**
 * Ask for a short-lived signed URL for one installer.
 *
 * The server returns the URL rather than redirecting, so the checksum can be
 * shown beside the link and the operator can verify what they downloaded.
 */
export async function requestPosDownload(
  releaseId: string,
  csrfToken: string,
): Promise<PosDownloadGrant> {
  const response = await fetch(`/api/hq/pos-releases/${encodeURIComponent(releaseId)}/download/`, {
    method: 'POST',
    credentials: 'include',
    headers: { Accept: 'application/json', 'X-CSRFToken': csrfToken },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new HQApiError(
      response.status,
      (detail as { detail?: string }).detail ?? `Download request failed with ${response.status}.`,
    );
  }
  return (await response.json()) as PosDownloadGrant;
}

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
  readonly cash_exception_review: CashExceptionReview | null;
  /** The frozen figures as counted and signed. Rendered, never recomputed. */
  readonly snapshot: ShiftReportSnapshot;
}

export interface CashExceptionReview {
  readonly id: string;
  readonly report_number: string;
  readonly status: 'UNDER_REVIEW' | 'RESOLVED';
  readonly opened_by_username: string;
  readonly opened_at: string;
  readonly opening_note: string;
  readonly resolved_by_username: string;
  readonly resolved_at: string | null;
  readonly resolution_note: string;
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
export const loadOpenRegisterSessions = (tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<RegisterSessionSummary>('/api/pos/shift/sessions/open/', tenantId, signal);

/** Sessions in a closing state without an authoritative final Z report. */
export const loadUnclosedRegisterSessions = (tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<RegisterSessionSummary>('/api/pos/shift/sessions/unclosed/', tenantId, signal);

/** Z reports whose counted cash did not match expected. */
export const loadCashVariances = (tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<ShiftReportSummary>('/api/pos/shift/reports/variances/', tenantId, signal);

/** Closures performed by somebody other than the accountable operator. */
export const loadForcedClosures = (tenantId = '', signal?: AbortSignal) =>
  getTenantCollection<ShiftReportSummary>('/api/pos/shift/reports/forced-closures/', tenantId, signal);

export const startCashExceptionReview = (
  reportId: string,
  note: string,
  csrfToken: string,
) => mutateJson<CashExceptionReview>(
  `/api/pos/shift/reports/${encodeURIComponent(reportId)}/start-cash-review/`,
  'POST',
  { note },
  csrfToken,
);

export const resolveCashExceptionReview = (
  reportId: string,
  note: string,
  csrfToken: string,
) => mutateJson<CashExceptionReview>(
  `/api/pos/shift/reports/${encodeURIComponent(reportId)}/resolve-cash-review/`,
  'POST',
  { note },
  csrfToken,
);

/* ── display helpers ───────────────────────────────────────────────────────── */

/**
 * Format a decimal string for display without going through a JS number.
 *
 * Prefer the shared helper so HQ, Windows POS and Android POS render the same
 * two-place amounts. Local re-export keeps existing HQ imports stable.
 */
export { formatMoney } from '@dawatrace/shared/money.js';

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

export interface PasswordForgotResult {
  readonly detail: string;
  /** Present only when the API is running with DEBUG=true. */
  readonly dev_reset_uid?: string;
  readonly dev_reset_token?: string;
}

/**
 * Request a password reset.
 *
 * The server always returns a generic success message so the form cannot be
 * used to enumerate accounts. In DEBUG it may also return a reset token for
 * local HQ use without email infrastructure.
 */
export async function requestPasswordReset(
  identity: { readonly email?: string; readonly username?: string },
  csrfToken: string,
): Promise<PasswordForgotResult> {
  const response = await fetch('/api/identity/password/forgot/', {
    method: 'POST',
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
    },
    body: JSON.stringify(identity),
  });

  const body = (await response.json().catch(() => null)) as
    | (PasswordForgotResult & { detail?: string })
    | null;

  if (!response.ok) {
    throw new SignInError(
      response.status,
      body?.detail ??
        (response.status === 429
          ? 'Too many attempts. Wait a moment before trying again.'
          : 'Password reset request failed.'),
    );
  }

  // The dev_reset_* keys are omitted entirely rather than set to undefined:
  // under exactOptionalPropertyTypes an explicit undefined is not assignable
  // to an optional property.
  return {
    detail: body?.detail ?? 'If an account matches that identity, password reset instructions have been prepared.',
    ...(body?.dev_reset_uid === undefined ? {} : { dev_reset_uid: body.dev_reset_uid }),
    ...(body?.dev_reset_token === undefined ? {} : { dev_reset_token: body.dev_reset_token }),
  };
}

/** Confirm a password reset with uid + token from the forgot step. */
export async function confirmPasswordReset(
  payload: { readonly uid: string; readonly token: string; readonly password: string },
  csrfToken: string,
): Promise<string> {
  const response = await fetch('/api/identity/password/reset/', {
    method: 'POST',
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
    },
    body: JSON.stringify(payload),
  });

  const body = (await response.json().catch(() => null)) as { detail?: string } | null;

  if (!response.ok) {
    throw new SignInError(
      response.status,
      body?.detail ??
        (response.status === 429
          ? 'Too many attempts. Wait a moment before trying again.'
          : 'Password reset failed.'),
    );
  }

  return body?.detail ?? 'Password updated. You can sign in with your new password.';
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
  tenantId: string,
  filters: ClaimFilters = {},
  signal?: AbortSignal,
): Promise<readonly InsuranceClaim[]> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) query.set(key, value);
  }
  const suffix = query.toString();
  return getTenantCollection<InsuranceClaim>(
    `/api/insurance/claims/${suffix ? `?${suffix}` : ''}`,
    tenantId,
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

/* ── inventory subsystem ─────────────────────────────────────────────────── */

export interface HQInventoryLocationItem {
  readonly branch: string;
  readonly id: string;
  readonly location_code: string;
  readonly name: string;
  readonly location_type: string;
  readonly status: string;
  readonly branch_name?: string;
  readonly cold_chain_capability?: boolean;
  readonly controlled_drug_capability?: boolean;
  readonly quarantine_capability?: boolean;
  readonly returns_capability?: boolean;
}

export interface HQInventoryBalanceItem {
  readonly inventory_batch?: string | null;
  readonly id: string;
  readonly location: string;
  readonly sku: string;
  readonly sku_code?: string;
  readonly sku_name?: string;
  readonly location_name?: string;
  readonly batch_number?: string;
  readonly on_hand: string;
  readonly reserved: string;
  readonly quarantined: string;
  readonly damaged: string;
  readonly expired: string;
  readonly available: string;
  readonly quality_status?: string;
  readonly expiry_status?: string;
}

export interface HQInventoryLedgerItem {
  readonly inventory_batch?: string | null;
  readonly id: string;
  readonly entry_type: string;
  readonly sku_code?: string;
  readonly location_name?: string;
  readonly batch_number?: string;
  readonly quantity_delta: string;
  readonly base_quantity_delta: string;
  readonly unit: string;
  readonly source_document_type: string;
  readonly source_document_id: string;
  readonly source_line_id?: string | null;
  readonly transaction_timestamp: string;
  readonly reason_code?: string;
  readonly notes?: string;
}

export interface HQInventoryBatchItem {
  readonly id: string;
  readonly sku: string;
  readonly sku_code?: string;
  readonly manufacturer_batch_number: string;
  readonly manufacture_date: string | null;
  readonly expiry_date: string;
  readonly quality_status: string;
  readonly recall_status: string;
}

export interface HQInventoryReservationItem {
  readonly id: string;
  readonly sku_code?: string;
  readonly location_name?: string;
  readonly batch_number?: string | null;
  readonly requested_quantity: string;
  readonly allocated_quantity: string;
  readonly status: string;
  readonly created_at: string;
}

export interface HQStockTransferAllocation {
  readonly batch_id: string;
  readonly batch_number: string;
  readonly dispatched_quantity: string;
  readonly received_quantity: string;
  readonly damaged_quantity: string;
  readonly remaining_quantity: string;
}

export interface HQStockTransferLine {
  readonly id: string;
  readonly sku: string;
  readonly sku_code: string;
  readonly sku_name: string;
  readonly batch: string | null;
  readonly batch_number: string | null;
  readonly requested_quantity: string;
  readonly allocated_quantity: string;
  readonly dispatched_quantity: string;
  readonly received_quantity: string;
  readonly rejected_quantity: string;
  readonly damaged_quantity: string;
  readonly unit: string;
  readonly discrepancy_reason: string;
  readonly dispatch_allocations: readonly HQStockTransferAllocation[];
}

export interface HQStockTransfer {
  readonly id: string;
  readonly transfer_number: string;
  readonly source_branch: string;
  readonly source_branch_name: string;
  readonly destination_branch: string;
  readonly destination_branch_name: string;
  readonly source_location: string;
  readonly source_location_name: string;
  readonly destination_location: string;
  readonly destination_location_name: string;
  readonly status: string;
  readonly requested_by_username: string | null;
  readonly approved_by_username: string | null;
  readonly dispatched_by_username: string | null;
  readonly received_by_username: string | null;
  readonly dispatch_timestamp: string | null;
  readonly receipt_timestamp: string | null;
  readonly reason: string;
  readonly document_reference: string;
  readonly lines: readonly HQStockTransferLine[];
  readonly created_at: string;
  readonly updated_at: string;
}

export interface HQStockTransferDraft {
  readonly transfer_number: string;
  readonly source_location: string;
  readonly destination_location: string;
  readonly reason: string;
  readonly document_reference: string;
  readonly lines: readonly {
    readonly sku: string;
    readonly quantity: string;
  }[];
}

export interface HQStockTransferReceipt {
  readonly idempotency_key: string;
  readonly lines: readonly {
    readonly line_id: string;
    readonly batch_id: string;
    readonly quantity: string;
    readonly damaged: string;
    readonly discrepancy_reason: string;
  }[];
}

export const loadInventoryLocations = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<HQInventoryLocationItem>('/api/inventory/locations/', tenantId, signal);

export const loadInventoryBalances = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<HQInventoryBalanceItem>('/api/inventory/balances/', tenantId, signal);

export const loadInventoryLedger = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<HQInventoryLedgerItem>('/api/inventory/ledger/', tenantId, signal);

export const loadInventoryBatches = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<HQInventoryBatchItem>('/api/inventory/batches/', tenantId, signal);

export const loadInventoryReservations = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<HQInventoryReservationItem>('/api/inventory/reservations/', tenantId, signal);

export const loadStockTransfers = (tenantId: string, signal?: AbortSignal) =>
  getTenantCollection<HQStockTransfer>('/api/inventory/transfers/', tenantId, signal);

export const createStockTransfer = (
  payload: HQStockTransferDraft,
  tenantId: string,
  csrfToken: string,
) => mutateJson<HQStockTransfer>(
  '/api/inventory/transfers/',
  'POST',
  payload,
  csrfToken,
  tenantId,
);

export const approveStockTransfer = (
  transferId: string,
  tenantId: string,
  csrfToken: string,
) => mutateJson<HQStockTransfer>(
  `/api/inventory/transfers/${transferId}/approve/`,
  'POST',
  {},
  csrfToken,
  tenantId,
);

export const dispatchStockTransfer = (
  transferId: string,
  tenantId: string,
  csrfToken: string,
) => mutateJson<HQStockTransfer>(
  `/api/inventory/transfers/${transferId}/dispatch/`,
  'POST',
  {},
  csrfToken,
  tenantId,
);

export const receiveStockTransfer = (
  transferId: string,
  payload: HQStockTransferReceipt,
  tenantId: string,
  csrfToken: string,
) => mutateJson<HQStockTransfer>(
  `/api/inventory/transfers/${transferId}/receive/`,
  'POST',
  payload,
  csrfToken,
  tenantId,
);

/* ── sales & fulfilment subsystem ────────────────────────────────────────── */

export interface HQQuotationItem {
  readonly id: string;
  readonly quotation_number: string;
  readonly customer_name?: string;
  readonly total: Money;
  readonly currency: string;
  readonly status: string;
  readonly issue_date: string;
  readonly valid_until: string | null;
}

export interface HQPickingWaveItem {
  readonly id: string;
  readonly wave_number: string;
  readonly status: string;
  readonly created_at: string;
}

export interface HQPickingTaskItem {
  readonly id: string;
  readonly sales_order_number?: string;
  readonly sku_code?: string;
  readonly requested_quantity: string;
  readonly picked_quantity: string;
  readonly status: string;
}

export interface HQPackingSessionItem {
  readonly id: string;
  readonly session_number: string;
  readonly sales_order_number?: string;
  readonly status: string;
}

export interface HQPackageItem {
  readonly id: string;
  readonly package_number: string;
  readonly sales_order_number?: string;
  readonly temperature_zone: string;
  readonly status: string;
}

export interface HQDeliveryRecordItem {
  readonly id: string;
  readonly dispatch_number?: string;
  readonly recipient_name?: string;
  readonly status: string;
  readonly delivered_at: string | null;
}

export interface HQSalesReturnItem {
  readonly id: string;
  readonly return_number: string;
  readonly sales_order_number?: string;
  readonly customer_name?: string;
  readonly status: string;
  readonly reason?: string;
}

export interface HQSalesOrderHoldItem {
  readonly id: string;
  readonly sales_order_number?: string;
  readonly hold_type: string;
  readonly reason: string;
  readonly is_active: boolean;
  readonly placed_at: string;
}

export const loadQuotations = (signal?: AbortSignal) =>
  getCollection<HQQuotationItem>('/api/sales/quotations/', signal);

export const loadPickingWaves = (signal?: AbortSignal) =>
  getCollection<HQPickingWaveItem>('/api/sales/picking-waves/', signal);

export const loadPickingTasks = (signal?: AbortSignal) =>
  getCollection<HQPickingTaskItem>('/api/sales/picking-tasks/', signal);

export const loadPackingSessions = (signal?: AbortSignal) =>
  getCollection<HQPackingSessionItem>('/api/sales/packing-sessions/', signal);

export const loadPackages = (signal?: AbortSignal) =>
  getCollection<HQPackageItem>('/api/sales/packages/', signal);

export const loadDeliveryRecords = (signal?: AbortSignal) =>
  getCollection<HQDeliveryRecordItem>('/api/sales/deliveries/', signal);

export const loadSalesReturns = (signal?: AbortSignal) =>
  getCollection<HQSalesReturnItem>('/api/sales/returns/', signal);

export const loadSalesOrderHolds = (signal?: AbortSignal) =>
  getCollection<HQSalesOrderHoldItem>('/api/sales/order-holds/', signal);
