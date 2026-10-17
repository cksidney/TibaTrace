import { action, deriveStages, fontFamily, fontSize, nextAction, spacing, surface, text, viewportAtMost } from '@dawatrace/shared/design-system/index.js';
import { paymentPermitsSupply, type TimelineEntry } from '@dawatrace/shared/dispensing/index.js';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { ClinicalRail } from './components/tibatrace/ClinicalRail.js';
import { ClinicalReviewWorkspace, type ClinicalOverrideActionInput } from './components/tibatrace/ClinicalReviewWorkspace.js';
import { CollectionPanel, CounsellingPanel } from './components/tibatrace/CounsellingAndCollection.js';
import { PatientSafetyBanner } from './components/tibatrace/PatientSafetyBanner.js';
import { OperationalStatusBar } from './components/tibatrace/OperationalStatusBar.js';
import { PaymentPanel } from './components/tibatrace/PaymentPanel.js';
import { PrintCentre } from './components/tibatrace/PrintCentre.js';
import { RegisterCentre } from './components/tibatrace/RegisterCentre.js';
import { PrescriptionWorkspace } from './components/tibatrace/PrescriptionWorkspace.js';
import { ClinicalPreparation } from './components/tibatrace/ClinicalPreparation.js';
import { EpisodeTimeline } from './components/tibatrace/EpisodeTimeline.js';
import { TaskQueue } from './components/tibatrace/TaskQueue.js';
import { RetailWorkspace } from './components/tibatrace/RetailWorkspace.js';
import { SyncCentre } from './components/tibatrace/SyncCentre.js';
import { PosActivationConsole } from './components/tibatrace/PosActivationConsole.js';
import type { PatientSummary } from './components/tibatrace/PatientSafetyBanner.js';
import { BlockingReason } from './components/tibatrace/StatusBadge.js';
import { WorkflowRibbon } from './components/tibatrace/WorkflowRibbon.js';
import { SHORTCUTS, resolveShortcut } from './state/keyboard.js';
import { useClinicalScreening } from './state/useClinicalScreening.js';
import { usePosWorkflow } from './state/usePosWorkflow.js';
import { useViewport } from './state/useViewport.js';
import { createPosRuntime } from './runtime.js';

const runtime = createPosRuntime();

/**
 * TibaTrace Windows clinical operations console.
 *
 * Four persistent regions: header, patient banner, workspace + clinical rail,
 * contextual action bar. The rail is never hidden behind a modal, so what is
 * blocking the operator stays on screen while they work.
 */
export function App() {
  const [session, setSession] = useState<TibaTraceSessionInfo | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    runtime
      .restore()
      .then(setSession)
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : String(cause));
        setSession({
          authenticated: false,
          tenantId: '',
          userId: '',
          deviceId: '',
          apiBaseUrl: '',
        });
      })
      .finally(() => setRestoring(false));
  }, []);
  useEffect(() => {
    if (!session?.authenticated) return;
    const timer = setInterval(() => {
      void runtime.restore().then(setSession).catch(() => setSession((current) => current ? { ...current, activationValid: false } : null));
    }, 60000);
    return () => clearInterval(timer);
  }, [session?.authenticated]);

  if (restoring) {
    return <CenteredMessage message="Restoring secure till session…" />;
  }
  if (!session?.authenticated) {
    return (
      <SignInScreen
        initialError={error}
        onSignIn={async (username, password) => {
          const signedIn = await runtime.login(username, password);
          setError('');
          setSession(signedIn);
        }}
      />
    );
  }

  return (
    <OperationsConsole
      key={`${session.userId}:${Boolean(session.activationValid)}`}
      session={session}
      onActivationRefresh={async () => setSession(await runtime.restore())}
      apiFetch={runtime.fetch}
      onLogout={async () => {
        await runtime.logout();
        setSession({ ...session, authenticated: false, tenantId: '', userId: '' });
      }}
    />
  );
}

export type EpisodeStep = 'items' | 'payment' | 'handover' | 'timeline';

function OperationsConsole({
  session,
  apiFetch,
  onLogout,
  onActivationRefresh,
}: {
  readonly session: TibaTraceSessionInfo;
  readonly apiFetch: typeof fetch;
  readonly onLogout: () => Promise<void>;
  readonly onActivationRefresh: () => Promise<void>;
}) {
  const [workspace, setWorkspace] = useState<
    'clinical' | 'retail' | 'register' | 'print' | 'sync' | 'activation'
  >(session.activationValid ? 'clinical' : 'activation');
  const { state, refreshQueue, select, refresh, takePayment, confirmCollection, recordCounselling, journal } =
    usePosWorkflow('/api/pos/dispensing', apiFetch, runtime.offline, session.deviceId);
  // Was `useState<ClinicalSummary | null>(null)` with no setter, so the rail
  // rendered "No clinical result" for every episode and the screening endpoint
  // had no caller anywhere in the repository.
  const { summary: clinical, result: clinicalResult, error: clinicalError, refresh: refreshClinical } = useClinicalScreening(state.selected, {
    deviceId: session.deviceId,
    fetcher: apiFetch,
  });
  const [reviewFindingId, setReviewFindingId] = useState('');
  const [clinicalReviewBusy, setClinicalReviewBusy] = useState(false);
  const [clinicalReviewError, setClinicalReviewError] = useState('');
  const [locked, setLocked] = useState(false);
  const [authority, setAuthority] = useState<{ owner: boolean; capabilities: readonly string[]; mustChangePassword: boolean } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void apiFetch('/api/identity/me/', { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('Authority unavailable');
        return response.json() as Promise<{ is_platform_admin?: boolean; is_superuser?: boolean; effective_capabilities?: string[]; must_change_password?: boolean }>;
      })
      .then((user) => setAuthority({ owner: Boolean(user.is_platform_admin || user.is_superuser), capabilities: user.effective_capabilities ?? [], mustChangePassword: Boolean(user.must_change_password) }))
      .catch(() => setAuthority(null));
    return () => controller.abort();
  }, [apiFetch]);
  const viewport = useViewport();
  // Below `expanded` the rail cannot hold its 320px and leave the workspace a
  // usable width, so it moves under the workspace instead of beside it. It is
  // still on the page -- a blocking finding must never be a screen away.
  const railBeside = !viewportAtMost(viewport, 'medium');

  useEffect(() => {
    if (session.activationValid) void refreshQueue();
  }, [refreshQueue, session.activationValid]);

  const stages = useMemo(
    () =>
      deriveStages(state.selected, {
        screened: clinical?.screened ?? false,
        safeToProceed: clinical?.safeToProceed ?? false,
        stale: clinical?.stale ?? false,
        pharmacistReviewRequired: (clinical?.blockingCount ?? 0) > 0,
      }),
    [state.selected, clinical],
  );

  const next = nextAction(stages);
  const [activeStep, setActiveStep] = useState<EpisodeStep>('items');
  const [showKeyboardHelp, setShowKeyboardHelp] = useState(false);

  useEffect(() => {
    if (!state.selected) {
      setActiveStep('items');
      return;
    }
    if (state.selected.status === 'READY_FOR_PAYMENT') {
      setActiveStep('payment');
    } else if (
      state.selected.status === 'PAID' ||
      state.selected.status === 'READY_FOR_SUPPLY' ||
      state.selected.status === 'READY_FOR_COLLECTION' ||
      state.selected.status === 'PARTIALLY_SUPPLIED' ||
      state.selected.status === 'SUPPLIED' ||
      state.selected.status === 'CLOSED'
    ) {
      setActiveStep('handover');
    } else {
      setActiveStep('items');
    }
  }, [state.selected?.id, state.selected?.status]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const command = resolveShortcut(event);
      if (!command) return;

      if (command === 'HELP') {
        event.preventDefault();
        setShowKeyboardHelp((open) => !open);
      } else if (command === 'CLOSE') {
        if (showKeyboardHelp) {
          event.preventDefault();
          setShowKeyboardHelp(false);
        } else if (reviewFindingId) {
          event.preventDefault();
          setReviewFindingId('');
        } else if (state.selected) {
          event.preventDefault();
          void select(null);
        }
      } else if (command === 'REFRESH') {
        event.preventDefault();
        void refresh();
        void refreshClinical();
      } else if (command === 'PRESCRIPTION' || command === 'PREPARATION') {
        event.preventDefault();
        setActiveStep('items');
      } else if (command === 'PAYMENT') {
        event.preventDefault();
        setActiveStep('payment');
      } else if (command === 'CLINICAL_FINDINGS' || command === 'PHARMACIST_REVIEW') {
        event.preventDefault();
        const firstFinding = clinicalResult?.findings[0];
        if (firstFinding) {
          setReviewFindingId(firstFinding.id);
        } else {
          setActiveStep('items');
        }
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [showKeyboardHelp, reviewFindingId, state.selected, clinicalResult, refresh, refreshClinical, select]);

  const activeRibbonStage = useMemo(() => {
    if (activeStep === 'payment') return 'PAYMENT';
    if (activeStep === 'handover') {
      return state.selected?.collected_at ? 'COLLECTION' : 'SUPPLY';
    }
    if (activeStep === 'timeline') return undefined;
    return stages.find((s) => s.state !== 'COMPLETE' && s.state !== 'NOT_STARTED')?.id ?? 'PRESCRIPTION';
  }, [activeStep, state.selected?.collected_at, stages]);
  const patient: PatientSummary | null = state.selected
    ? {
        // The resolved name, not `patient`, which is the row's UUID. This
        // banner is what an operator reads to confirm who they are dispensing
        // for, and it previously showed them a foreign key.
        fullName: state.selected.patient_name ?? 'Name not recorded',
        reference: state.selected.patient_number ?? state.selected.dispensing_number,
        ...(state.selected.patient_date_of_birth
          ? { dateOfBirth: state.selected.patient_date_of_birth }
          : {}),
        ...(state.selected.patient_sex ? { sex: state.selected.patient_sex } : {}),
        // An empty list means the record is silent, which is not the clinical
        // claim "no known allergies" -- so it maps to UNKNOWN, the amber
        // action-required state, rather than to the green NONE_KNOWN. Only a
        // positive assertion of no allergies would justify the latter, and the
        // server has no field that makes one.
        allergyStatus: state.selected.allergies.length > 0 ? 'KNOWN_ALLERGY' : 'UNKNOWN',
        badges: [],
        ...(state.selected.prescription_number
          ? { prescriptionRef: state.selected.prescription_number }
          : {}),
      }
    : null;

  const requestClinicalReview = async () => {
    if (!clinicalResult) return;
    setClinicalReviewBusy(true);
    setClinicalReviewError('');
    try {
      const response = await apiFetch(`/api/pos/clinical-screening/${clinicalResult.screeningId}/request-pharmacist/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ cashier_id: session.userId, expected_context_hash: clinicalResult.contextHash }),
      });
      if (!response.ok) throw new Error(`The pharmacist review request was refused (${response.status}).`);
    } catch (cause) {
      setClinicalReviewError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setClinicalReviewBusy(false);
    }
  };

  const submitClinicalDecision = async (input: { decision: string; clinicalJustification: string; conditions: string; followUpActions: string }) => {
    if (!clinicalResult) return;
    setClinicalReviewBusy(true);
    setClinicalReviewError('');
    try {
      const response = await apiFetch(`/api/pos/clinical-screening/${clinicalResult.screeningId}/pharmacist-review/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          finding_id: reviewFindingId,
          decision: input.decision,
          clinical_justification: input.clinicalJustification,
          conditions: input.conditions,
          follow_up_actions: input.followUpActions,
          idempotency_key: `POS-WINDOWS-CLINICAL-${Date.now()}-${Math.random().toString(16).slice(2)}`,
          expected_context_hash: clinicalResult.contextHash,
        }),
      });
      if (!response.ok) throw new Error(`The clinical decision was refused (${response.status}).`);
      await refreshClinical();
      setReviewFindingId('');
    } catch (cause) {
      setClinicalReviewError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setClinicalReviewBusy(false);
    }
  };

  const submitClinicalOverride = async (input: ClinicalOverrideActionInput) => {
    if (!clinicalResult) return;
    setClinicalReviewBusy(true);
    setClinicalReviewError('');
    try {
      const idempotencyKey = `POS-WINDOWS-OVERRIDE-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      let path = '/api/pos/clinical-screening/overrides/';
      let body: Record<string, string> = {};

      if (input.action === 'request') {
        body = {
          screening_id: clinicalResult.screeningId,
          finding_id: input.findingId,
          override_reason: input.overrideReason ?? 'CLINICALLY_JUSTIFIED',
          requested_reason: input.requestedReason ?? '',
          supporting_notes: input.supportingNotes ?? '',
          idempotency_key: idempotencyKey,
          expected_context_hash: clinicalResult.contextHash,
        };
      } else {
        if (!input.overrideId) throw new Error('The override record is missing. Refresh the clinical result and try again.');
        path = `/api/pos/clinical-screening/overrides/${input.overrideId}/${input.action}/`;
        if (input.action === 'start-review') {
          body = {};
        } else if (input.action === 'approve') {
          body = {
            clinical_justification: input.clinicalJustification ?? '',
            conditions: input.conditions ?? '',
            ...(input.expiresAt ? { expires_at: input.expiresAt } : {}),
            idempotency_key: idempotencyKey,
            expected_context_hash: clinicalResult.contextHash,
          };
        } else if (input.action === 'reject') {
          body = { rejection_reason: input.reason ?? '' };
        } else {
          body = { revocation_reason: input.reason ?? '' };
        }
      }

      const response = await apiFetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`The override action was refused (${response.status}).`);
      await refreshClinical();
    } catch (cause) {
      setClinicalReviewError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setClinicalReviewBusy(false);
    }
  };

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateRows: 'auto auto auto auto 1fr auto',
        // dvh, not vh: on a phone the browser chrome is subtracted from dvh, so
        // the action bar sits above the address bar instead of under it. The
        // height is only pinned once the workspace scrolls internally; on a
        // stacked layout the document scrolls as a whole.
        minHeight: '100dvh',
        height: railBeside ? '100dvh' : undefined,
        fontFamily: fontFamily.sans,
        background: surface.page,
        color: text.primary,
      }}
    >
      <Header
        busy={state.busy}
        operator={session.username ?? session.userId}
        workspace={workspace}
        onWorkspaceChange={(next) => setWorkspace(session.activationValid ? next : 'activation')}
        onLock={() => setLocked(true)}
        onLogout={onLogout}
        onOpenHelp={() => setShowKeyboardHelp(true)}
      />
      <OperationalStatusBar
        apiFetch={apiFetch}
        deviceId={session.deviceId}
      />
      {workspace === 'retail' ? (
        <RetailWorkspace apiFetch={apiFetch} deviceId={session.deviceId} />
      ) : workspace === 'register' ? (
        <RegisterCentre apiFetch={apiFetch} deviceId={session.deviceId} />
      ) : workspace === 'print' ? (
        <PrintCentre apiFetch={apiFetch} deviceId={session.deviceId} />
      ) : workspace === 'sync' ? (
        <SyncCentre apiFetch={apiFetch} deviceId={session.deviceId} journal={journal} onOpenPrint={() => setWorkspace('print')} />
      ) : workspace === 'activation' ? (
        <PosActivationConsole
          apiFetch={apiFetch}
          userId={session.userId}
          userRole={authority?.owner ? 'PLATFORM_OWNER' : 'TENANT_USER'}
          userCapabilities={authority?.owner ? ['platform.pos_activation.approve', 'platform.pos_activation.review'] : authority?.capabilities ?? []}
          isPlatformOwnerContext={authority?.owner ?? false}
          tenantId={session.tenantId}
          deviceId={session.deviceId}
          fingerprint={session.deviceFingerprint ?? ''}
          appVersion={session.appVersion ?? ''}
          onEnrolled={onActivationRefresh}
          passwordChangeRequired={authority?.mustChangePassword ?? false}
        />
      ) : <>
      <PatientSafetyBanner patient={patient} />
      <WorkflowRibbon
        stages={stages}
        activeStage={activeRibbonStage}
        onSelect={(stageId) => {
          if (stageId === 'PAYMENT') {
            setActiveStep('payment');
          } else if (stageId === 'SUPPLY' || stageId === 'COLLECTION') {
            setActiveStep('handover');
          } else if (stageId === 'CLINICAL_SCREENING' || stageId === 'PHARMACIST_VERIFICATION') {
            setActiveStep('items');
            if (clinical?.blockingCount && clinicalResult?.findings[0]) {
              setReviewFindingId(clinicalResult.findings[0].id);
            }
          } else {
            setActiveStep('items');
          }
        }}
      />

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: railBeside
            ? `minmax(0, 1fr) clamp(300px, 24vw, 360px)`
            : 'minmax(0, 1fr)',
          minHeight: 0,
        }}
      >
        <main
          style={{
            padding: viewportAtMost(viewport, 'compact') ? spacing.md : spacing.xl,
            overflowY: railBeside ? 'auto' : 'visible',
            minWidth: 0,
          }}
        >
          {state.notice ? (
            <div style={{ marginBottom: spacing.lg }}>
              <BlockingReason
                status={state.notice.kind === 'unknown' ? 'STALE' : 'BLOCKING'}
                reason={state.notice.message}
              />
            </div>
          ) : null}

          {state.selected ? (
            clinicalResult && reviewFindingId ? (
              <ClinicalReviewWorkspace
                result={clinicalResult}
                findingId={reviewFindingId}
                patientName={state.selected.patient_name ?? 'Name not recorded'}
                prescriptionReference={state.selected.prescription_number ?? state.selected.dispensing_number}
                busy={clinicalReviewBusy}
                error={clinicalReviewError}
                onBack={() => setReviewFindingId('')}
                onRequestReview={() => void requestClinicalReview()}
                onSubmit={(input) => void submitClinicalDecision(input)}
                onOverrideAction={(input) => void submitClinicalOverride(input)}
              />
            ) : (
            <div style={{ display: 'grid', gap: spacing.lg }}>
              <EpisodeWorkspace
                episode={state.selected}
                gateReason={state.gate.blockedReason}
                onRefresh={() => void refresh()}
                onBackToQueue={() => void select(null)}
              />

              <EpisodeStepNav
                activeStep={activeStep}
                onStepChange={setActiveStep}
                linesCount={state.selected.lines.length}
                preparedCount={state.selected.lines.filter((l) => l.status === 'PREPARED').length}
                paymentState={state.selected.payment_state}
                isCollected={Boolean(state.selected.collected_at)}
              />

              {activeStep === 'items' ? (
                <div style={{ display: 'grid', gap: spacing.xl }}>
                  <ClinicalPreparation key={state.selected.id} episode={state.selected} apiFetch={apiFetch} onChanged={() => void refresh()} />
                  <PrescriptionWorkspace
                    lines={state.selected.lines}
                    apiFetch={apiFetch}
                    episodeId={state.selected.id}
                    onTransition={() => void refresh()}
                  />
                  {state.gate.canTakePayment ? (
                    <div
                      style={{
                        padding: `${spacing.md}px ${spacing.lg}px`,
                        borderRadius: 10,
                        background: '#ECFDF5',
                        border: '1px solid #10B981',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: spacing.md,
                        flexWrap: 'wrap',
                      }}
                    >
                      <div>
                        <strong style={{ color: '#065F46', fontSize: fontSize.body }}>All prescription items prepared</strong>
                        <p style={{ margin: '2px 0 0 0', color: '#047857', fontSize: fontSize.caption }}>
                          Lines verified and allocated. Proceed to payment settlement to authorise supply.
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setActiveStep('payment')}
                        style={{
                          padding: '10px 18px',
                          borderRadius: 8,
                          border: 'none',
                          background: '#059669',
                          color: '#fff',
                          fontWeight: 700,
                          cursor: 'pointer',
                          fontSize: fontSize.body,
                          minHeight: 40,
                        }}
                      >
                        Proceed to Payment [F8] →
                      </button>
                    </div>
                  ) : null}
                </div>
              ) : activeStep === 'payment' ? (
                <section id="payment-workspace" style={{ display: 'grid', gap: spacing.xl }}>
                  <PaymentPanel
                    paymentState={state.selected.payment_state}
                    amountDue={state.selected.amount_due ?? null}
                    amountSettled={state.selected.amount_settled ?? null}
                    canTakePayment={state.gate.canTakePayment}
                    blockedReason={state.gate.canTakePayment ? '' : state.gate.blockedReason}
                    busy={state.busy}
                    onTakePayment={(tender, amount, reference) =>
                      void takePayment(tender, amount, reference)
                    }
                  />
                  {paymentPermitsSupply(state.selected.payment_state) ? (
                    <div
                      style={{
                        padding: `${spacing.md}px ${spacing.lg}px`,
                        borderRadius: 10,
                        background: '#ECFDF5',
                        border: '1px solid #10B981',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: spacing.md,
                        flexWrap: 'wrap',
                      }}
                    >
                      <div>
                        <strong style={{ color: '#065F46', fontSize: fontSize.body }}>Payment Settled</strong>
                        <p style={{ margin: '2px 0 0 0', color: '#047857', fontSize: fontSize.caption }}>
                          Authorised transaction journaled. Proceed to patient counselling and handover.
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setActiveStep('handover')}
                        style={{
                          padding: '10px 18px',
                          borderRadius: 8,
                          border: 'none',
                          background: '#059669',
                          color: '#fff',
                          fontWeight: 700,
                          cursor: 'pointer',
                          fontSize: fontSize.body,
                          minHeight: 40,
                        }}
                      >
                        Proceed to Handover →
                      </button>
                    </div>
                  ) : null}
                </section>
              ) : activeStep === 'handover' ? (
                <div style={{ display: 'grid', gap: spacing.xl }}>
                  <CounsellingPanel
                    counsellingStatus={state.selected.counselling_status}
                    busy={state.busy}
                    onRecord={(request) => void recordCounselling(request)}
                  />
                  <section id="collection-workspace">
                    <CollectionPanel
                      canConfirm={state.gate.canConfirmCollection}
                      blockedReason={state.gate.canConfirmCollection ? '' : state.gate.blockedReason}
                      collectedAt={state.selected.collected_at ?? null}
                      collectorName={state.selected.collector_name}
                      busy={state.busy}
                      onConfirm={(name, id, relationship) =>
                        void confirmCollection(name, id, relationship)
                      }
                    />
                  </section>
                </div>
              ) : (
                <EpisodeTimelineSection
                  episodeId={state.selected.id}
                  apiFetch={apiFetch}
                />
              )}
            </div>
            )
          ) : (
            <Queue
              queue={state.queue}
              busy={state.busy}
              onSelect={(id) => void select(id)}
              apiFetch={apiFetch}
              operator={session.userId}
            />
          )}
        </main>

        <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          {/* Why the screening is unavailable, stated rather than left as an
              unexplained empty rail. An operator who cannot tell a failed
              request from an unscreened basket will assume the latter. */}
          {clinicalError ? (
            <div style={{ padding: spacing.md }}>
              <BlockingReason status="ACTION_REQUIRED" reason={clinicalError} />
            </div>
          ) : null}
          <ClinicalRail
            summary={clinical}
            onOpenReview={(findingId) => {
              setClinicalReviewError('');
              setReviewFindingId(findingId);
            }}
          />
        </div>
      </div>

      <ActionBar
        nextLabel={next ? next.label : 'No action available'}
        canTakePayment={state.gate.canTakePayment}
        canConfirmCollection={state.gate.canConfirmCollection}
        onOpenPayment={() => setActiveStep('payment')}
        onOpenCollection={() => setActiveStep('handover')}
        onOpenHelp={() => setShowKeyboardHelp(true)}
      />
      {showKeyboardHelp ? (
        <KeyboardHelpModal onClose={() => setShowKeyboardHelp(false)} />
      ) : null}
      </>}
      {locked ? (
        <WorkstationLock
          initialUsername={session.username ?? ''}
          onUnlock={async (username, password) => {
            if (!(await runtime.verify(username, password))) {
              throw new Error('Those credentials do not match the operator who locked this workstation.');
            }
            setLocked(false);
          }}
          onSignOut={onLogout}
        />
      ) : null}
    </div>
  );
}

function Header({
  busy,
  operator,
  workspace,
  onWorkspaceChange,
  onLock,
  onLogout,
  onOpenHelp,
}: {
  readonly busy: boolean;
  readonly operator: string;
  readonly workspace: 'clinical' | 'retail' | 'register' | 'print' | 'sync' | 'activation';
  readonly onWorkspaceChange: (workspace: 'clinical' | 'retail' | 'register' | 'print' | 'sync' | 'activation') => void;
  readonly onLock: () => void;
  readonly onLogout: () => Promise<void>;
  readonly onOpenHelp?: () => void;
}) {
  const viewport = useViewport();
  const compact = viewportAtMost(viewport, 'compact');

  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        // Wraps rather than compressing: the workspace tabs and the lock and
        // sign-out controls all stay full size and reachable, on a second row
        // if the width cannot hold one.
        flexWrap: 'wrap',
        rowGap: spacing.sm,
        columnGap: spacing.lg,
        padding: `${spacing.sm}px ${compact ? spacing.md : spacing.xl}px`,
        background: surface.inverse,
        color: action.primaryForeground,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm }}>
        <div
          style={{
            width: 40,
            height: 40,
            overflow: 'hidden',
            borderRadius: 10,
            background: '#fff',
            flex: '0 0 auto',
          }}
        >
          <img
            src="./brand/tibatrace-logo.jpeg"
            alt="TibaTrace logo"
            style={{ display: 'block', width: 100, height: 100, maxWidth: 'none', transform: 'translate(-29px, -15px)' }}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <strong style={{ fontSize: fontSize.bodyLarge, letterSpacing: 0.3 }}>TibaTrace</strong>
          {compact ? null : (
            <span style={{ fontSize: fontSize.caption, opacity: 0.8 }}>Clinical operations console</span>
          )}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {(['clinical', 'retail', 'register', 'print', 'sync', 'activation'] as const).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onWorkspaceChange(option)}
            style={{
              minHeight: 34,
              padding: '4px 10px',
              border: '1px solid rgba(255,255,255,0.35)',
              borderRadius: 7,
            background: workspace === option ? text.inverse : 'transparent',
            color: workspace === option ? surface.inverse : text.inverse,
              fontWeight: 700,
              cursor: 'pointer',
              textTransform: 'capitalize',
            }}
          >
            {option === 'print' ? 'Print Centre' : option === 'sync' ? 'Sync Centre' : option}
          </button>
        ))}
      </div>
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: spacing.md, flexWrap: 'wrap' }}>
        <span style={{ fontSize: fontSize.caption, opacity: 0.8 }}>
          {/* The operator's name, not a truncated primary key. Falls back to
              the id only when the server did not send a username. */}
          {busy ? 'Working…' : operator || 'Signed in'}
        </span>
        {onOpenHelp ? (
          <button
            type="button"
            onClick={onOpenHelp}
            style={{
              minHeight: 36,
              padding: '6px 12px',
              border: '1px solid rgba(255,255,255,0.35)',
              borderRadius: 8,
              background: 'transparent',
              color: action.primaryForeground,
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: 12,
            }}
          >
            Shortcuts [F1]
          </button>
        ) : null}
        <button
          type="button"
          onClick={onLock}
          style={{
            minHeight: 36,
            padding: '6px 12px',
            border: '1px solid rgba(255,255,255,0.35)',
            borderRadius: 8,
          background: text.inverse,
            color: surface.inverse,
            cursor: 'pointer',
            fontWeight: 700,
          }}
        >
          Lock
        </button>
        <button
          type="button"
          onClick={() => void onLogout()}
          style={{
            minHeight: 36,
            padding: '6px 12px',
            border: '1px solid rgba(255,255,255,0.35)',
            borderRadius: 8,
            background: 'transparent',
          color: action.primaryForeground,
            cursor: 'pointer',
          }}
        >
          Sign out
        </button>
      </div>
    </header>
  );
}

function WorkstationLock({
  initialUsername,
  onUnlock,
  onSignOut,
}: {
  readonly initialUsername: string;
  readonly onUnlock: (username: string, password: string) => Promise<void>;
  readonly onSignOut: () => Promise<void>;
}) {
  const [username, setUsername] = useState(initialUsername);
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="workstation-lock-title"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        display: 'grid',
        placeItems: 'center',
        padding: spacing.xl,
        background: surface.inverse,
        color: action.primaryForeground,
      }}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setBusy(true);
          setError('');
          void onUnlock(username.trim(), password)
            .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)))
            .finally(() => {
              setBusy(false);
              setPassword('');
            });
        }}
        style={{
          width: 'min(420px, 100%)',
          display: 'grid',
          gap: spacing.md,
          padding: spacing.xxl,
          borderRadius: 16,
          background: surface.raised,
          color: text.primary,
          boxShadow: '0 24px 72px rgba(0,0,0,0.48)',
        }}
      >
        <img src="./brand/tibatrace-logo.jpeg" alt="TibaTrace" style={{ width: 150, maxWidth: '100%', margin: '0 auto' }} />
        <div>
          <h1 id="workstation-lock-title" style={{ margin: 0, fontSize: fontSize.screenTitle }}>Workstation locked</h1>
          <p style={{ marginBottom: 0, color: text.secondary }}>The current operator must re-verify their credentials. Register and shift accountability do not change.</p>
        </div>
        {error ? <BlockingReason status="BLOCKING" reason={error} /> : null}
        <label style={{ display: 'grid', gap: spacing.xs, fontSize: fontSize.caption }}>Username
          <input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required maxLength={150} style={lockInput} />
        </label>
        <label style={{ display: 'grid', gap: spacing.xs, fontSize: fontSize.caption }}>Password
          <input autoFocus type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required maxLength={256} style={lockInput} />
        </label>
        <button type="submit" disabled={busy || !username.trim() || !password} style={lockPrimary(busy || !username.trim() || !password)}>
          {busy ? 'Verifying…' : 'Unlock workstation'}
        </button>
        <button type="button" disabled={busy} onClick={() => void onSignOut()} style={lockSecondary}>Sign out instead</button>
      </form>
    </div>
  );
}

function CenteredMessage({ message }: { readonly message: string }) {
  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        background: surface.page,
        color: text.secondary,
        fontFamily: fontFamily.sans,
      }}
    >
      <p>{message}</p>
    </main>
  );
}

const lockInput = {
  minHeight: 44,
  border: `1px solid ${surface.borderStrong}`,
  borderRadius: 8,
  padding: '0 12px',
  fontSize: fontSize.body,
};
const lockPrimary = (disabled: boolean) => ({
  minHeight: 44,
  border: 'none',
  borderRadius: 8,
  background: disabled ? surface.sunken : action.primary,
  color: disabled ? text.tertiary : '#fff',
  fontSize: fontSize.body,
  fontWeight: 700,
  cursor: disabled ? 'not-allowed' : 'pointer',
});
const lockSecondary = {
  minHeight: 40,
  border: `1px solid ${surface.borderStrong}`,
  borderRadius: 8,
  background: surface.raised,
  color: text.primary,
  fontSize: fontSize.caption,
  fontWeight: 700,
  cursor: 'pointer',
};

function SignInScreen({
  initialError,
  onSignIn,
}: {
  readonly initialError: string;
  readonly onSignIn: (username: string, password: string) => Promise<void>;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialError);
  const viewport = useViewport();
  // The hero column needs roughly 300px before its 42px headline starts
  // breaking words. Below `expanded` it goes under the form instead.
  const sideBySide = !viewportAtMost(viewport, 'medium');

  return (
    <main
      style={{
        minHeight: '100dvh',
        display: 'grid',
        placeItems: 'center',
        padding: viewportAtMost(viewport, 'compact') ? spacing.lg : spacing.xxl,
        boxSizing: 'border-box',
        background: `linear-gradient(135deg, ${surface.inverse} 0%, #14243B 52%, #0D403A 100%)`,
        fontFamily: fontFamily.sans,
        color: action.primaryForeground,
      }}
    >
      <div
        style={{
          width: 'min(1080px, 100%)',
          display: 'grid',
          gridTemplateColumns: sideBySide
            ? 'minmax(300px, 1.15fr) minmax(380px, 0.85fr)'
            : 'minmax(0, 1fr)',
          gap: sideBySide ? spacing.xxxl : spacing.xl,
          alignItems: 'center',
        }}
      >
        <section
          aria-labelledby="pos-welcome-title"
          style={{
            maxWidth: 560,
            // Once stacked, the form is what the operator came for; the hero
            // copy moves below it rather than pushing sign-in off the fold.
            order: sideBySide ? 0 : 1,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.md, marginBottom: spacing.xxl }}>
            <div style={{ width: 52, height: 52, overflow: 'hidden', borderRadius: 14, background: text.inverse }}>
              <img
                src="./brand/tibatrace-logo.jpeg"
                alt=""
                style={{ display: 'block', width: 130, height: 130, maxWidth: 'none', transform: 'translate(-38px, -20px)' }}
              />
            </div>
            <div style={{ display: 'grid', gap: 2 }}>
              <strong style={{ fontSize: fontSize.medicineName }}>TibaTrace</strong>
              <span style={{ fontSize: fontSize.caption, opacity: 0.75, letterSpacing: 0.8 }}>CLINICAL OPERATIONS</span>
            </div>
          </div>
          <p style={{ margin: 0, color: '#6EE7D0', fontSize: fontSize.caption, fontWeight: 700, letterSpacing: 1.4, textTransform: 'uppercase' }}>
            Trace. Trust. Health.
          </p>
          <h1
            id="pos-welcome-title"
            style={{ margin: `${spacing.md}px 0`, maxWidth: 520, fontSize: 'clamp(28px, 5vw, 42px)', lineHeight: 1.08 }}
          >
            Safe dispensing starts with a trusted operator.
          </h1>
          <p style={{ maxWidth: 520, margin: 0, color: '#CBD5E1', fontSize: fontSize.bodyLarge, lineHeight: 1.6 }}>
            One secure workstation for prescription review, clinical screening,
            payment, counselling and collection.
          </p>
          <div style={{ display: 'flex', gap: spacing.sm, flexWrap: 'wrap', marginTop: spacing.xl }}>
            {['Clinical safety', 'Offline resilience', 'Audited actions'].map((feature) => (
              <span key={feature} style={{ padding: `${spacing.sm}px ${spacing.md}px`, border: '1px solid rgba(255,255,255,0.18)', borderRadius: 999, fontSize: fontSize.caption, color: '#E2E8F0' }}>
                {feature}
              </span>
            ))}
          </div>
        </section>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setBusy(true);
            setError('');
            void onSignIn(username.trim(), password)
              .catch((cause: unknown) =>
                setError(cause instanceof Error ? cause.message : String(cause)),
              )
              .finally(() => setBusy(false));
          }}
          style={{
            display: 'grid',
            gap: spacing.md,
            padding: viewportAtMost(viewport, 'compact') ? spacing.lg : spacing.xxl,
            border: '1px solid rgba(255,255,255,0.16)',
            borderRadius: 20,
            background: surface.raised,
            color: text.primary,
            boxShadow: '0 28px 80px rgba(0, 0, 0, 0.32)',
            minWidth: 0,
          }}
        >
          <div>
            <p style={{ margin: `0 0 ${spacing.sm}px`, color: action.primary, fontSize: fontSize.caption, fontWeight: 700, letterSpacing: 0.8, textTransform: 'uppercase' }}>Protected workstation</p>
            <h2 style={{ margin: 0, fontSize: fontSize.screenTitle }}>Sign in to Windows POS</h2>
            <p style={{ color: text.secondary, marginBottom: 0 }}>Use your assigned TibaTrace operator account.</p>
          </div>
          {error ? <BlockingReason status="BLOCKING" reason={error} /> : null}
          <label style={{ display: 'grid', gap: spacing.xs, fontSize: fontSize.caption, fontWeight: 600 }}>
            Email or username
            <input
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
              maxLength={150}
              style={lockInput}
            />
          </label>
          <label style={{ display: 'grid', gap: spacing.xs, fontSize: fontSize.caption, fontWeight: 600 }}>
            Password
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              maxLength={256}
              style={lockInput}
            />
          </label>
          <button
            type="submit"
            disabled={busy || !username.trim() || !password}
            style={{
              minHeight: 48,
              border: 'none',
              borderRadius: 10,
              background: busy || !username.trim() || !password ? action.disabled : action.primary,
              color: busy || !username.trim() || !password ? action.disabledForeground : action.primaryForeground,
              fontSize: fontSize.body,
              fontWeight: 700,
              cursor: busy || !username.trim() || !password ? 'not-allowed' : 'pointer',
            }}
          >
            {busy ? 'Signing in…' : 'Sign in securely'}
          </button>
          <small style={{ color: text.tertiary, lineHeight: 1.5 }}>
            Access is encrypted, audited and restricted to authorised pharmacy staff.
          </small>
        </form>
      </div>
    </main>
  );
}

function Queue({
  queue,
  busy,
  onSelect,
  apiFetch,
  operator,
}: {
  readonly queue: readonly {
    id: string;
    dispensing_number: string;
    status: string;
    patient_name?: string | null;
    patient_number?: string | null;
  }[];
  readonly busy: boolean;
  readonly onSelect: (id: string) => void;
  readonly apiFetch?: typeof fetch;
  readonly operator?: string;
}) {
  const [tasks, setTasks] = useState<readonly import('@dawatrace/shared/dispensing/index.js').ClinicalTask[]>([]);

  useEffect(() => {
    if (!apiFetch) return;
    void apiFetch('/api/pos/clinical-screening/tasks/', { headers: { Accept: 'application/json' } })
      .then(async (r) => {
        if (!r.ok) return;
        const data = await r.json() as { results?: unknown[] } | unknown[];
        const items = Array.isArray(data) ? data : ((data as { results?: unknown[] }).results ?? []);
        setTasks(items as import('@dawatrace/shared/dispensing/index.js').ClinicalTask[]);
      })
      .catch(() => undefined);
  }, [apiFetch]);

  if (busy && queue.length === 0) {
    return <p style={{ color: text.secondary }}>Loading dispensing queue…</p>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.xl }}>
      {tasks.length > 0 ? (
        <div>
          <TaskQueue
            tasks={tasks}
            {...(operator ? { currentUser: operator } : {})}
            onOpen={(episodeId) => onSelect(episodeId)}
          />
        </div>
      ) : null}
      <div>
        <h2 style={{ fontSize: fontSize.sectionTitle, margin: `0 0 ${spacing.md}px` }}>Dispensing queue</h2>
        {queue.length === 0 ? (
          <p style={{ color: text.secondary }}>No prescriptions waiting. Scan or search for a prescription to begin.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.sm }}>
            {queue.map((episode) => (
              <button
                key={episode.id}
                type="button"
                onClick={() => onSelect(episode.id)}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  flexWrap: 'wrap',
                  gap: spacing.sm,
                  padding: spacing.md,
                  borderRadius: 10,
                  border: `1px solid ${surface.border}`,
                  background: surface.raised,
                  cursor: 'pointer',
                  fontSize: fontSize.body,
                  minHeight: 48,
                  textAlign: 'left',
                }}
              >
                {/* The patient leads, not the dispensing number.
                    The row showed only the number, so an operator choosing from a
                    queue of several could not tell who was who without opening each
                    one -- on the screen where picking the wrong person is the error
                    that matters most. The Android queue already led with the name.
                    An episode with no name on file says so rather than falling back
                    to the number, which would read as a patient called DEMO-DISP-8001. */}
                <span style={{ display: 'grid', gap: 2 }}>
                  <span style={{ fontWeight: 600 }}>
                    {episode.patient_name ?? 'Name not recorded'}
                  </span>
                  <span
                    style={{
                      color: text.secondary,
                      fontSize: fontSize.caption,
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    {episode.patient_number ? `${episode.patient_number} · ` : ''}
                    {episode.dispensing_number}
                  </span>
                </span>
                <span style={{ color: text.secondary }}>{episode.status.replace(/_/g, ' ')}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Fetches and renders the audit timeline for a dispensing episode.
 *
 * Loaded on demand: the timeline is not in the episode DTO, and fetching it
 * eagerly for every episode that opens would add a second round-trip to the
 * critical path. The section renders a loading placeholder and fills in
 * once the response arrives.
 */
function EpisodeTimelineSection({
  episodeId,
  apiFetch,
}: {
  readonly episodeId: string;
  readonly apiFetch: typeof fetch;
}) {
  const [entries, setEntries] = useState<readonly TimelineEntry[] | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const response = await apiFetch(
        `/api/pos/dispensing/episodes/${episodeId}/timeline/`,
        { headers: { Accept: 'application/json' } },
      );
      if (!response.ok) { setError(`Timeline unavailable (${response.status}).`); return; }
      const data = await response.json() as TimelineEntry[] | { results?: TimelineEntry[] };
      setEntries(Array.isArray(data) ? data : (data.results ?? []));
    } catch {
      setError('Timeline could not be loaded.');
    }
  }, [apiFetch, episodeId]);

  useEffect(() => { void load(); }, [load]);

  if (error) {
    return (
      <section>
        <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>History</h2>
        <p style={{ color: text.secondary, fontSize: fontSize.caption }}>{error}</p>
      </section>
    );
  }
  if (entries === null) {
    return (
      <section>
        <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>History</h2>
        <p style={{ color: text.secondary, fontSize: fontSize.caption }}>Loading episode history…</p>
      </section>
    );
  }
  return <EpisodeTimeline entries={entries} />;
}

function EpisodeWorkspace({
  episode,
  gateReason,
  onRefresh,
  onBackToQueue,
}: {
  readonly episode: { dispensing_number: string; status: string; payment_state: string };
  readonly gateReason: string;
  readonly onRefresh: () => void;
  readonly onBackToQueue: () => void;
}) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: spacing.md, justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: spacing.md, flexWrap: 'wrap' }}>
          <button
            type="button"
            onClick={onBackToQueue}
            aria-label="Return to queue"
            title="Return to patient queue (Escape)"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 12px',
              borderRadius: 8,
              border: `1px solid ${surface.borderStrong}`,
              background: surface.raised,
              color: text.primary,
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: fontSize.caption,
              minHeight: 34,
            }}
          >
            <span>← Queue</span>
            <kbd style={{ fontSize: 10, opacity: 0.65, border: '1px solid rgba(0,0,0,0.2)', padding: '1px 4px', borderRadius: 4 }}>Esc</kbd>
          </button>

          <h2 style={{ fontSize: fontSize.sectionTitle, margin: 0, fontVariantNumeric: 'tabular-nums' }}>
            {episode.dispensing_number}
          </h2>

          <span
            style={{
              padding: '3px 8px',
              borderRadius: 6,
              background: episode.status === 'CLOSED' || episode.status === 'SUPPLIED' ? '#ECFDF5' : '#EFF6FF',
              color: episode.status === 'CLOSED' || episode.status === 'SUPPLIED' ? '#065F46' : '#1E40AF',
              border: `1px solid ${episode.status === 'CLOSED' || episode.status === 'SUPPLIED' ? '#A7F3D0' : '#BFDBFE'}`,
              fontSize: 12,
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: 0.5,
            }}
          >
            {episode.status.replace(/_/g, ' ')}
          </span>

          <span
            style={{
              padding: '3px 8px',
              borderRadius: 6,
              background: episode.payment_state === 'PAID' || episode.payment_state === 'WAIVED' ? '#ECFDF5' : '#FEF3C7',
              color: episode.payment_state === 'PAID' || episode.payment_state === 'WAIVED' ? '#065F46' : '#92400E',
              border: `1px solid ${episode.payment_state === 'PAID' || episode.payment_state === 'WAIVED' ? '#A7F3D0' : '#FDE68A'}`,
              fontSize: 12,
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: 0.5,
            }}
          >
            {episode.payment_state.replace(/_/g, ' ')}
          </span>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          title="Refresh authoritative state (Ctrl+R)"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '6px 12px',
            borderRadius: 8,
            border: `1px solid ${surface.borderStrong}`,
            background: surface.raised,
            cursor: 'pointer',
            minHeight: 34,
            fontSize: fontSize.caption,
            fontWeight: 600,
          }}
        >
          <span>Refresh</span>
          <kbd style={{ fontSize: 10, opacity: 0.65, border: '1px solid rgba(0,0,0,0.2)', padding: '1px 4px', borderRadius: 4 }}>Ctrl+R</kbd>
        </button>
      </div>

      {gateReason ? (
        <div style={{ marginTop: spacing.md }}>
          <BlockingReason status="BLOCKING" reason={gateReason} />
        </div>
      ) : null}
    </div>
  );
}

function EpisodeStepNav({
  activeStep,
  onStepChange,
  linesCount,
  preparedCount,
  paymentState,
  isCollected,
}: {
  readonly activeStep: EpisodeStep;
  readonly onStepChange: (step: EpisodeStep) => void;
  readonly linesCount: number;
  readonly preparedCount: number;
  readonly paymentState: string;
  readonly isCollected: boolean;
}) {
  const steps: {
    id: EpisodeStep;
    label: string;
    shortcut: string;
    badge: string;
    badgeColor?: string | undefined;
  }[] = [
    {
      id: 'items',
      label: 'Prescription & Items',
      shortcut: 'F4',
      badge: `${preparedCount}/${linesCount} prepared`,
      badgeColor: preparedCount === linesCount && linesCount > 0 ? '#10B981' : undefined,
    },
    {
      id: 'payment',
      label: 'Payment & Billing',
      shortcut: 'F8',
      badge: paymentState.replace(/_/g, ' '),
      badgeColor: paymentState === 'PAID' || paymentState === 'WAIVED' ? '#10B981' : undefined,
    },
    {
      id: 'handover',
      label: 'Handover & Counselling',
      shortcut: 'F10',
      badge: isCollected ? 'Collected' : 'Pending',
      badgeColor: isCollected ? '#10B981' : undefined,
    },
    {
      id: 'timeline',
      label: 'Timeline & Audit',
      shortcut: '',
      badge: 'History',
    },
  ];

  return (
    <nav
      aria-label="Episode workflow steps"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: spacing.xs,
        padding: 4,
        background: surface.sunken,
        borderRadius: 10,
        marginTop: spacing.sm,
        overflowX: 'auto',
      }}
    >
      {steps.map((s) => {
        const isActive = activeStep === s.id;
        return (
          <button
            key={s.id}
            type="button"
            onClick={() => onStepChange(s.id)}
            style={{
              flex: 1,
              minWidth: 160,
              padding: '8px 12px',
              borderRadius: 8,
              border: 'none',
              background: isActive ? surface.raised : 'transparent',
              color: isActive ? text.primary : text.secondary,
              boxShadow: isActive ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
              cursor: 'pointer',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 2,
              transition: 'background 0.15s ease',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontWeight: isActive ? 700 : 500, fontSize: fontSize.body }}>
                {s.label}
              </span>
              {s.shortcut ? (
                <kbd
                  style={{
                    fontSize: 10,
                    padding: '1px 4px',
                    borderRadius: 4,
                    background: isActive ? 'rgba(0,0,0,0.06)' : 'rgba(0,0,0,0.03)',
                    border: '1px solid rgba(0,0,0,0.1)',
                    color: text.secondary,
                  }}
                >
                  {s.shortcut}
                </kbd>
              ) : null}
            </div>
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: s.badgeColor ?? text.tertiary,
              }}
            >
              {s.badge}
            </span>
          </button>
        );
      })}
    </nav>
  );
}

function KeyboardHelpModal({ onClose }: { readonly onClose: () => void }) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="keyboard-help-title"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        display: 'grid',
        placeItems: 'center',
        padding: spacing.xl,
        background: 'rgba(0, 0, 0, 0.65)',
        backdropFilter: 'blur(4px)',
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: 'min(520px, 100%)',
          background: surface.raised,
          borderRadius: 14,
          padding: spacing.xl,
          boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
          color: text.primary,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.lg }}>
          <h2 id="keyboard-help-title" style={{ margin: 0, fontSize: fontSize.screenTitle }}>
            Keyboard Shortcuts
          </h2>
          <button
            type="button"
            onClick={onClose}
            style={{
              border: `1px solid ${surface.borderStrong}`,
              background: 'transparent',
              borderRadius: 6,
              padding: '4px 8px',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            Esc
          </button>
        </div>
        <p style={{ margin: '0 0 16px 0', fontSize: fontSize.caption, color: text.secondary }}>
          The till is fully operable without a mouse. High-frequency actions map to function keys:
        </p>
        <div style={{ display: 'grid', gap: spacing.sm }}>
          {SHORTCUTS.map((s) => (
            <div
              key={s.key}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '6px 10px',
                borderRadius: 6,
                background: surface.sunken,
              }}
            >
              <span style={{ fontSize: fontSize.body }}>{s.label}</span>
              <kbd
                style={{
                  fontFamily: 'monospace',
                  fontWeight: 700,
                  fontSize: 12,
                  padding: '2px 8px',
                  borderRadius: 4,
                  background: surface.raised,
                  border: `1px solid ${surface.borderStrong}`,
                }}
              >
                {s.ctrl ? `Ctrl + ${s.key}` : s.key}
              </kbd>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ActionBar({
  nextLabel,
  canTakePayment,
  canConfirmCollection,
  onOpenPayment,
  onOpenCollection,
  onOpenHelp,
}: {
  readonly nextLabel: string;
  readonly canTakePayment: boolean;
  readonly canConfirmCollection: boolean;
  readonly onOpenPayment: () => void;
  readonly onOpenCollection: () => void;
  readonly onOpenHelp?: () => void;
}) {
  const primary = canTakePayment
    ? { label: 'Review payment [F8]', onClick: onOpenPayment }
    : canConfirmCollection
      ? { label: 'Review collection [F10]', onClick: onOpenCollection }
      : null;

  return (
    <footer
      style={{
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: spacing.md,
        padding: `${spacing.sm}px clamp(${spacing.md}px, 3vw, ${spacing.xl}px)`,
        background: surface.raised,
        borderTop: `1px solid ${surface.border}`,
        position: 'sticky',
        bottom: 0,
        zIndex: 1,
        minHeight: 48,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: spacing.md }}>
        <span style={{ fontSize: fontSize.caption, color: text.secondary }}>Next: {nextLabel}</span>
        {onOpenHelp ? (
          <button
            type="button"
            onClick={onOpenHelp}
            style={{
              padding: '2px 8px',
              borderRadius: 6,
              border: `1px solid ${surface.borderStrong}`,
              background: surface.sunken,
              color: text.secondary,
              fontSize: 11,
              fontWeight: 600,
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            <span>Shortcuts</span>
            <kbd style={{ fontSize: 10, opacity: 0.7 }}>F1</kbd>
          </button>
        ) : null}
      </div>

      <div style={{ marginLeft: 'auto', display: 'flex', gap: spacing.sm, flexWrap: 'wrap', alignItems: 'center' }}>
        {primary ? (
          <PrimaryButton onClick={primary.onClick}>{primary.label}</PrimaryButton>
        ) : (
          <span style={{ alignSelf: 'center', color: text.tertiary, fontSize: fontSize.caption }}>
            Complete the required clinical or workflow step to continue.
          </span>
        )}
      </div>
    </footer>
  );
}

function PrimaryButton({
  onClick,
  children,
}: {
  readonly onClick: () => void;
  readonly children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        padding: '10px 18px',
        borderRadius: 8,
        border: 'none',
        background: action.primary,
        color: action.primaryForeground,
        fontSize: fontSize.body,
        fontWeight: 600,
        cursor: 'pointer',
        minHeight: 44,
      }}
    >
      {children}
    </button>
  );
}
