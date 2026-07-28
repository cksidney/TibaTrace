/**
 * Visual-regression scenario catalogue.
 *
 * Each scenario renders one component in one fixed state. Everything is
 * hard-coded: no network, no clock, no randomness, no persisted state. A
 * screenshot diff must mean the rendering changed, not that the data did.
 *
 * The catalogue deliberately over-weights the states that are dangerous to get
 * wrong. A payment button is a visual bug; a blocking banner that collapses to
 * zero height, or a status badge that loses its colour and its icon at the same
 * time, is a dispensing incident. Those states appear here in every variant.
 */
import type { ClinicalFinding, ClinicalSummary } from '../src/components/tibatrace/ClinicalRail.js';
import { ClinicalRail } from '../src/components/tibatrace/ClinicalRail.js';
import { PatientSafetyBanner } from '../src/components/tibatrace/PatientSafetyBanner.js';
import type { PatientSummary } from '../src/components/tibatrace/PatientSafetyBanner.js';
import { PaymentPanel } from '../src/components/tibatrace/PaymentPanel.js';
import { PrintCentre } from '../src/components/tibatrace/PrintCentre.js';
import { RegisterCentre } from '../src/components/tibatrace/RegisterCentre.js';
import { SyncCentre } from '../src/components/tibatrace/SyncCentre.js';
import { BlockingReason, StatusBadge } from '../src/components/tibatrace/StatusBadge.js';
import { WorkflowRibbon } from '../src/components/tibatrace/WorkflowRibbon.js';
import type { ClinicalStatus } from '@dawatrace/shared/design-system/index.js';
import type { StageView } from '@dawatrace/shared/design-system/index.js';
import type { OfflineAction } from '@dawatrace/shared/dispensing/index.js';
import type { ReactNode } from 'react';

const visualFetch: typeof fetch = async () => new Response(null, { status: 503 });
const recoveryEntry: OfflineAction = {
  id: 'journal-action-1',
  type: 'PAYMENT',
  episodeId: 'episode-8c30d0c0',
  idempotencyKey: 'payment:episode-8c30d0c0:attempt-42',
  payload: {},
  state: 'NEEDS_RECONCILIATION',
  queuedAt: '2026-07-28T09:30:00.000Z',
  sentAt: '2026-07-28T09:30:01.000Z',
  resolvedAt: '2026-07-28T09:30:02.000Z',
  failureReason: 'The application restarted while this payment was in flight. Its outcome is unknown until the server is queried.',
  attempts: 1,
};

export interface Scenario {
  readonly id: string;
  readonly title: string;
  /** Why this state is in the catalogue. Read during baseline review. */
  readonly rationale: string;
  readonly width: number;
  readonly render: () => ReactNode;
}

const ALL_STATUSES: readonly ClinicalStatus[] = [
  'SAFE',
  'INFORMATION',
  'ACTION_REQUIRED',
  'PHARMACIST_REVIEW',
  'BLOCKING',
  'STALE',
  'OFFLINE',
  'PROCESSING',
  'COMPLETED',
  'DISABLED',
];

function finding(overrides: Partial<ClinicalFinding> = {}): ClinicalFinding {
  return {
    id: 'f-1',
    severity: 'BLOCKING',
    category: 'Interaction',
    title: 'Warfarin and this medicine interact',
    explanation:
      'Concurrent use substantially increases bleeding risk. The combination is contraindicated at these doses.',
    recommendation: 'Contact the prescriber before supplying.',
    blocking: true,
    overrideAllowed: false,
    requiresPharmacist: true,
    ...overrides,
  };
}

function summary(overrides: Partial<ClinicalSummary> = {}): ClinicalSummary {
  return {
    safeToProceed: false,
    screened: true,
    stale: false,
    blockingCount: 1,
    findings: [finding()],
    connectivity: 'ONLINE',
    evaluatedAt: '2026-01-01T09:00:00.000Z',
    ...overrides,
  };
}

function patient(overrides: Partial<PatientSummary> = {}): PatientSummary {
  return {
    fullName: 'Grace Kamau',
    reference: 'PT-000412',
    dateOfBirth: '1958-04-11',
    age: '67',
    sex: 'F',
    allergyStatus: 'NONE_KNOWN',
    badges: ['NO_KNOWN_ALLERGIES'],
    prescriptionRef: 'RX-2026-0113',
    ...overrides,
  };
}

function stages(active: string, overrides: Partial<Record<string, Partial<StageView>>> = {}) {
  const base: readonly StageView[] = [
    { id: 'PATIENT', label: 'Patient', step: 1, state: 'COMPLETE', blockedReason: '', navigable: true },
    { id: 'PRESCRIPTION', label: 'Prescription', step: 2, state: 'COMPLETE', blockedReason: '', navigable: true },
    { id: 'CLINICAL_SCREENING', label: 'Screening', step: 3, state: 'IN_PROGRESS', blockedReason: '', navigable: true },
    { id: 'PHARMACIST_VERIFICATION', label: 'Verification', step: 4, state: 'NOT_STARTED', blockedReason: '', navigable: false },
    { id: 'PREPARATION', label: 'Preparation', step: 5, state: 'NOT_STARTED', blockedReason: '', navigable: false },
    { id: 'FINAL_CHECK', label: 'Final check', step: 6, state: 'NOT_STARTED', blockedReason: '', navigable: false },
    { id: 'PAYMENT', label: 'Payment', step: 7, state: 'NOT_STARTED', blockedReason: '', navigable: false },
    { id: 'SUPPLY', label: 'Supply', step: 8, state: 'NOT_STARTED', blockedReason: '', navigable: false },
    { id: 'COLLECTION', label: 'Collection', step: 9, state: 'NOT_STARTED', blockedReason: '', navigable: false },
  ];
  return {
    stages: base.map((stage) => ({ ...stage, ...(overrides[stage.id] ?? {}) })),
    activeStage: active,
  };
}

export const SCENARIOS: readonly Scenario[] = [
  // ------------------------------------------------------------ status badges
  {
    id: 'status-badge-all',
    title: 'Status badges — every status',
    rationale:
      'Colour is never the only signal. Each badge must show a distinct label and icon, so a status stays readable when colour is lost.',
    width: 420,
    render: () => (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {ALL_STATUSES.map((status) => (
          <StatusBadge key={status} status={status} />
        ))}
      </div>
    ),
  },
  {
    id: 'status-badge-small',
    title: 'Status badges — small variant',
    rationale: 'The compact badge used in dense lists must stay legible, not just smaller.',
    width: 420,
    render: () => (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {ALL_STATUSES.map((status) => (
          <StatusBadge key={status} status={status} size="sm" />
        ))}
      </div>
    ),
  },
  {
    id: 'blocking-reason-long',
    title: 'Blocking reason — long text',
    rationale:
      'A blocking reason must never be clipped or collapse to zero height. If the operator cannot read why they are blocked, they will look for a way around it.',
    width: 420,
    render: () => (
      <BlockingReason
        status="BLOCKING"
        reason="Supply is prohibited: the prescriber must be contacted because this combination substantially increases bleeding risk at the prescribed doses, and no override is available at this authority level."
      />
    ),
  },

  // ----------------------------------------------------------- safety banner
  {
    id: 'banner-no-known-allergies',
    title: 'Patient banner — no known allergies',
    rationale: 'The ordinary case. Establishes the baseline the risk states must visibly differ from.',
    width: 1280,
    render: () => <PatientSafetyBanner patient={patient()} />,
  },
  {
    id: 'banner-known-allergy',
    title: 'Patient banner — known allergy',
    rationale:
      'The highest-consequence banner state. It must be unmistakably different from the safe state at a glance across the counter.',
    width: 1280,
    render: () => (
      <PatientSafetyBanner
        patient={patient({
          allergyStatus: 'KNOWN_ALLERGY',
          badges: ['KNOWN_ALLERGY', 'HIGH_RISK_MEDICINE', 'OLDER_PATIENT'],
        })}
      />
    ),
  },
  {
    id: 'banner-allergy-unknown',
    title: 'Patient banner — allergy status unknown',
    rationale:
      'Unknown is not safe. This must not render like NONE_KNOWN — that collapse is exactly the three-valued bug the status type exists to prevent.',
    width: 1280,
    render: () => (
      <PatientSafetyBanner
        patient={patient({ allergyStatus: 'UNKNOWN', badges: ['ALLERGY_STATUS_UNKNOWN'] })}
      />
    ),
  },
  {
    id: 'banner-many-badges',
    title: 'Patient banner — many badges',
    rationale:
      'Badge overflow must not push the allergy status off-screen or wrap it out of the first line of sight.',
    width: 1280,
    render: () => (
      <PatientSafetyBanner
        patient={patient({
          allergyStatus: 'KNOWN_ALLERGY',
          badges: [
            'KNOWN_ALLERGY',
            'HIGH_RISK_MEDICINE',
            'CONTROLLED_MEDICINE',
            'PREGNANCY_ALERT',
            'RENAL_RISK',
            'OLDER_PATIENT',
            'REPEAT_DISPENSING',
          ],
        })}
      />
    ),
  },
  {
    id: 'banner-long-name',
    title: 'Patient banner — long name',
    rationale: 'A long name must not displace the safety badges.',
    width: 1280,
    render: () => (
      <PatientSafetyBanner
        patient={patient({
          fullName: 'Anastasia Wanjiru Njeri Kariuki-Mwangi',
          badges: ['KNOWN_ALLERGY', 'CONTROLLED_MEDICINE'],
          allergyStatus: 'KNOWN_ALLERGY',
        })}
      />
    ),
  },
  {
    id: 'banner-empty',
    title: 'Patient banner — no patient selected',
    rationale:
      'The empty banner must reserve its space. A banner that collapses to nothing lets the layout jump when a patient is chosen.',
    width: 1280,
    render: () => <PatientSafetyBanner patient={null} />,
  },

  // ------------------------------------------------------------ clinical rail
  {
    id: 'rail-blocking',
    title: 'Clinical rail — blocking finding',
    rationale: 'The rail stays on screen while blocked; the reason and the lawful next action must both be visible.',
    width: 380,
    render: () => <ClinicalRail summary={summary()} capabilities={new Set(['dispensing.read'])} />,
  },
  {
    id: 'rail-safe',
    title: 'Clinical rail — server says safe',
    rationale: 'Safe is an authoritative server answer. It must look different from "no findings loaded yet".',
    width: 380,
    render: () => (
      <ClinicalRail summary={summary({ safeToProceed: true, blockingCount: 0, findings: [] })} />
    ),
  },
  {
    id: 'rail-not-screened',
    title: 'Clinical rail — not yet screened',
    rationale:
      'An unscreened episode must not resemble a safe one. Absence of findings is not a pass.',
    width: 380,
    render: () => (
      <ClinicalRail
        summary={summary({ screened: false, safeToProceed: false, blockingCount: 0, findings: [] })}
      />
    ),
  },
  {
    id: 'rail-stale',
    title: 'Clinical rail — stale context',
    rationale: 'Staleness blocks progression. It must read as a block, not a hint.',
    width: 380,
    render: () => <ClinicalRail summary={summary({ stale: true })} />,
  },
  {
    id: 'rail-offline-verified-package',
    title: 'Clinical rail — offline with a verified package',
    rationale:
      'Offline but still able to dispense against a verified package. Must not look like the blocked offline state below.',
    width: 380,
    render: () => (
      <ClinicalRail
        summary={summary({
          connectivity: 'OFFLINE_VERIFIED_PACKAGE',
          safeToProceed: true,
          blockingCount: 0,
          findings: [],
        })}
      />
    ),
  },
  {
    id: 'rail-offline-blocked',
    title: 'Clinical rail — offline, dispensing blocked',
    rationale:
      'The two offline states permit opposite actions. If they render alike, an operator will dispense against a package that was never verified.',
    width: 380,
    render: () => (
      <ClinicalRail
        summary={summary({
          connectivity: 'OFFLINE_DISPENSING_BLOCKED',
          safeToProceed: false,
          blockingCount: 0,
          findings: [],
        })}
      />
    ),
  },
  {
    id: 'rail-sync-pending',
    title: 'Clinical rail — sync pending',
    rationale: 'Queued offline work must be visible, or it will be forgotten at shift end.',
    width: 380,
    render: () => (
      <ClinicalRail
        summary={summary({ connectivity: 'SYNC_PENDING', safeToProceed: true, blockingCount: 0, findings: [] })}
      />
    ),
  },
  {
    id: 'rail-null',
    title: 'Clinical rail — no summary',
    rationale:
      'A screening that could not be fetched is not a screening that passed. This must not render as safe.',
    width: 380,
    render: () => <ClinicalRail summary={null} />,
  },
  {
    id: 'rail-many-findings',
    title: 'Clinical rail — several findings',
    rationale: 'Findings must sort by severity, with the blocking one never scrolled out of first view.',
    width: 380,
    render: () => (
      <ClinicalRail
        summary={summary({
          blockingCount: 1,
          findings: [
            finding({
              id: 'f-3',
              severity: 'INFORMATION',
              category: 'Counselling',
              title: 'Take with food',
              explanation: 'Gastric irritation is common when this is taken on an empty stomach.',
              recommendation: 'Advise the patient to take each dose with a meal.',
              blocking: false,
              requiresPharmacist: false,
            }),
            finding({
              id: 'f-2',
              severity: 'ACTION_REQUIRED',
              category: 'Dosing',
              title: 'Renal dose adjustment may be needed',
              explanation: 'The last recorded creatinine clearance was below the standard-dose threshold.',
              recommendation: 'Confirm current renal function before supplying.',
              blocking: false,
              requiresPharmacist: false,
            }),
            finding({ id: 'f-1' }),
          ],
        })}
      />
    ),
  },

  // ---------------------------------------------------------- workflow ribbon
  {
    id: 'ribbon-screening',
    title: 'Workflow ribbon — at screening',
    rationale: 'The ribbon is the operator’s position sense. The active stage must be unambiguous.',
    width: 1280,
    render: () => <WorkflowRibbon {...stages('CLINICAL_SCREENING')} />,
  },
  {
    id: 'ribbon-blocked',
    title: 'Workflow ribbon — blocked at screening',
    rationale: 'A blocked stage must be distinguishable from a merely incomplete one.',
    width: 1280,
    render: () => (
      <WorkflowRibbon
        {...stages('CLINICAL_SCREENING', {
          CLINICAL_SCREENING: { state: 'BLOCKED', blockedReason: 'Blocking interaction unresolved.' },
        })}
      />
    ),
  },
  {
    id: 'ribbon-stale',
    title: 'Workflow ribbon — stale stage',
    rationale: 'Stale must not be mistaken for complete.',
    width: 1280,
    render: () => (
      <WorkflowRibbon
        {...stages('CLINICAL_SCREENING', {
          CLINICAL_SCREENING: { state: 'STALE', blockedReason: 'Clinical context changed.' },
        })}
      />
    ),
  },
  {
    id: 'ribbon-payment',
    title: 'Workflow ribbon — at payment',
    rationale: 'Late-stage position, with most stages complete.',
    width: 1280,
    render: () => (
      <WorkflowRibbon
        {...stages('PAYMENT', {
          CLINICAL_SCREENING: { state: 'COMPLETE' },
          PHARMACIST_VERIFICATION: { state: 'COMPLETE', navigable: true },
          PREPARATION: { state: 'COMPLETE', navigable: true },
          FINAL_CHECK: { state: 'COMPLETE', navigable: true },
          PAYMENT: { state: 'IN_PROGRESS', navigable: true },
        })}
      />
    ),
  },

  // ------------------------------------------------------------ payment panel
  {
    id: 'payment-ready',
    title: 'Payment — ready to take',
    rationale: 'The ordinary payment state, with tenders enabled.',
    width: 520,
    render: () => (
      <PaymentPanel
        paymentState="PENDING"
        amountDue="1250.00"
        amountSettled="0.00"
        canTakePayment
        blockedReason=""
        busy={false}
        onTakePayment={() => undefined}
      />
    ),
  },
  {
    id: 'payment-blocked',
    title: 'Payment — blocked by clinical state',
    rationale:
      'Controls must be visibly disabled with the reason shown. A disabled control with no explanation reads as a broken screen, and operators route around broken screens.',
    width: 520,
    render: () => (
      <PaymentPanel
        paymentState="PENDING"
        amountDue="1250.00"
        amountSettled="0.00"
        canTakePayment={false}
        blockedReason="Clinical screening has an unresolved blocking finding. Payment cannot be taken."
        busy={false}
        onTakePayment={() => undefined}
      />
    ),
  },
  {
    id: 'payment-busy',
    title: 'Payment — in flight',
    rationale:
      'While a payment is in flight the operator must not be able to send a second one. The busy state must be obvious, not a subtle opacity change.',
    width: 520,
    render: () => (
      <PaymentPanel
        paymentState="PENDING"
        amountDue="1250.00"
        amountSettled="0.00"
        canTakePayment
        blockedReason=""
        busy
        onTakePayment={() => undefined}
      />
    ),
  },
  {
    id: 'payment-partial',
    title: 'Payment — partially paid',
    rationale:
      'PARTIALLY_PAID does not permit supply. It must not look like PAID; the outstanding balance is the point.',
    width: 520,
    render: () => (
      <PaymentPanel
        paymentState="PARTIALLY_PAID"
        amountDue="1250.00"
        amountSettled="500.00"
        canTakePayment
        blockedReason=""
        busy={false}
        onTakePayment={() => undefined}
      />
    ),
  },
  {
    id: 'payment-paid',
    title: 'Payment — settled',
    rationale: 'A settled payment must close the panel down, not merely recolour it.',
    width: 520,
    render: () => (
      <PaymentPanel
        paymentState="PAID"
        amountDue="1250.00"
        amountSettled="1250.00"
        canTakePayment={false}
        blockedReason=""
        busy={false}
        onTakePayment={() => undefined}
      />
    ),
  },
  {
    id: 'payment-failed',
    title: 'Payment — failed',
    rationale: 'A failure must be distinguishable from a pending state, or the till will wait forever.',
    width: 520,
    render: () => (
      <PaymentPanel
        paymentState="FAILED"
        amountDue="1250.00"
        amountSettled="0.00"
        canTakePayment
        blockedReason=""
        busy={false}
        onTakePayment={() => undefined}
      />
    ),
  },
  {
    id: 'payment-reversal-pending',
    title: 'Payment — reversal pending',
    rationale:
      'An unusual state that operators rarely see, which is exactly why it must be self-explanatory when it appears.',
    width: 520,
    render: () => (
      <PaymentPanel
        paymentState="REVERSAL_PENDING"
        amountDue="1250.00"
        amountSettled="1250.00"
        canTakePayment={false}
        blockedReason="A reversal is in progress with the provider."
        busy={false}
        onTakePayment={() => undefined}
      />
    ),
  },
  {
    id: 'payment-unreadable-amount',
    title: 'Payment — amount could not be read',
    rationale:
      'A grouped or otherwise unparseable amount must show as unknown, never as NaN and never as 0.00. Zero is a claim that nothing is owed.',
    width: 520,
    render: () => (
      <PaymentPanel
        paymentState="PENDING"
        amountDue="1,250.00"
        amountSettled="0.00"
        canTakePayment
        blockedReason=""
        busy={false}
        onTakePayment={() => undefined}
      />
    ),
  },
  {
    id: 'payment-not-required',
    title: 'Payment — not required',
    rationale: 'Must not present tender controls at all.',
    width: 520,
    render: () => (
      <PaymentPanel
        paymentState="NOT_REQUIRED"
        amountDue={null}
        amountSettled={null}
        canTakePayment={false}
        blockedReason=""
        busy={false}
        onTakePayment={() => undefined}
      />
    ),
  },
  {
    id: 'print-centre-retry-required',
    title: 'Print Centre — simulator retry required',
    rationale:
      'A retry-required receipt must show both its immutable document identity and the transport failure without resembling a settled physical print.',
    width: 1024,
    render: () => (
      <PrintCentre
        apiFetch={visualFetch}
        deviceId="VISUAL-TILL-01"
        autoRefresh={false}
        initialJobs={[{
          id: 'job-1',
          document_number: 'RCP-DISP-2026-001-AB12CD34',
          document_type: 'PRESCRIPTION_RECEIPT',
          printer: '',
          transport: 'SIMULATOR',
          status: 'RETRY_REQUIRED',
          copy_classification: 'ORIGINAL',
          copy_number: 1,
          reprint_reason: '',
          requested_at: '2026-07-28T09:15:00.000Z',
          attempt_count: 1,
          failure_code: 'SIMULATED_TRANSPORT_FAILURE',
          failure_message: 'Deterministic simulator recorded a retryable transport failure.',
          printed_at: null,
          cancellation_reason: '',
        }]}
      />
    ),
  },
  {
    id: 'sync-centre-reconciliation',
    title: 'Sync Centre — unknown payment recovery',
    rationale:
      'An interrupted payment must make the blocked state, the exact recovery action and the no-blind-retry boundary readable at a glance.',
    width: 1024,
    render: () => (
      <SyncCentre
        apiFetch={visualFetch}
        deviceId="VISUAL-TILL-01"
        journal={null}
        onOpenPrint={() => undefined}
        autoRefresh={false}
        initialSnapshot={{
          entries: [recoveryEntry],
          runtime: { readiness: 'READY', notices: [] },
          clinicalConnected: true,
          printCounts: { queued: 1, retryRequired: 1 },
        }}
      />
    ),
  },
  {
    id: 'register-centre-open-shift',
    title: 'Register Centre — open shift with pending movement',
    rationale:
      'Register accountability, the pending second-person cash approval and the lawful X/Z actions must remain readable together at till resolution.',
    width: 1024,
    render: () => (
      <RegisterCentre
        apiFetch={visualFetch}
        deviceId="VISUAL-TILL-01"
        autoRefresh={false}
        initialRuntime={{
          readiness: 'READY',
          register: {
            id: 'register-1',
            code: 'TILL-01',
            name: 'Front counter',
            branch_code: 'NAI-CBD',
            device_id: 'VISUAL-TILL-01',
            currency: 'KES',
            state: 'OPEN',
            expected_float: '5000.00',
            last_synchronised_at: '2026-07-28T09:00:00.000Z',
          },
          business_day: {
            id: 'day-1',
            branch_code: 'NAI-CBD',
            business_date: '2026-07-28',
            state: 'OPEN',
            opened_at: '2026-07-28T06:00:00.000Z',
            closed_at: null,
            accepts_transactions: true,
            reopen_reason: '',
          },
          register_session: {
            id: 'session-1',
            register_code: 'TILL-01',
            business_date: '2026-07-28',
            state: 'OPEN',
            opened_at: '2026-07-28T06:30:00.000Z',
            opened_by_username: 'cashier.one',
            closed_at: null,
            closed_by_username: '',
            forced_closure: false,
            forced_closure_reason: '',
            has_final_report: false,
            operator_shifts: [{
              id: 'shift-1',
              operator_id: 'operator-1',
              operator_username: 'cashier.one',
              state: 'OPEN',
              started_at: '2026-07-28T06:30:00.000Z',
              ended_at: null,
              handed_over_to_username: '',
              close_reason: '',
            }],
          },
          operator_shift: {
            id: 'shift-1',
            operator_id: 'operator-1',
            operator_username: 'cashier.one',
            state: 'OPEN',
            started_at: '2026-07-28T06:30:00.000Z',
            ended_at: null,
            handed_over_to_username: '',
            close_reason: '',
          },
          device_health: null,
          notices: [],
          allowed_actions: ['START_SALE', 'REQUEST_HANDOVER', 'RECORD_CASH_MOVEMENT', 'APPROVE_CASH_MOVEMENT', 'GENERATE_X_REPORT', 'CLOSE_REGISTER'],
          closure_eligibility: {
            eligible: false,
            blocking_reasons: [
              'A confirmed closing cash declaration is required.',
              '1 cash movement(s) await approval.',
            ],
          },
        }}
        initialMovements={[{
          id: 'movement-1',
          kind: 'SAFE_DROP',
          amount: '25000.00',
          signed_amount: '-25000.00',
          affects_expected_cash: true,
          currency: 'KES',
          reason_code: 'SECURITY_THRESHOLD',
          description: 'Drawer exceeded the branch cash threshold.',
          reference: 'SAFE-2026-0142',
          created_by_username: 'cashier.one',
          approved_by_username: '',
          approved_at: null,
          created_at: '2026-07-28T08:45:00.000Z',
        }]}
        initialReports={[]}
      />
    ),
  },
];

export const SCENARIOS_BY_ID = new Map(SCENARIOS.map((scenario) => [scenario.id, scenario]));
