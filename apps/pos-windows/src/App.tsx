import { action, deriveStages, fontFamily, fontSize, nextAction, spacing, surface, text, viewportAtMost } from '@dawatrace/shared/design-system/index.js';
import type { TimelineEntry } from '@dawatrace/shared/dispensing/index.js';
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
import { EpisodeTimeline } from './components/tibatrace/EpisodeTimeline.js';
import { TaskQueue } from './components/tibatrace/TaskQueue.js';
import { RetailWorkspace } from './components/tibatrace/RetailWorkspace.js';
import { SyncCentre } from './components/tibatrace/SyncCentre.js';
import type { PatientSummary } from './components/tibatrace/PatientSafetyBanner.js';
import { BlockingReason } from './components/tibatrace/StatusBadge.js';
import { WorkflowRibbon } from './components/tibatrace/WorkflowRibbon.js';
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
      session={session}
      apiFetch={runtime.fetch}
      onLogout={async () => {
        await runtime.logout();
        setSession({ ...session, authenticated: false, tenantId: '', userId: '' });
      }}
    />
  );
}

function OperationsConsole({
  session,
  apiFetch,
  onLogout,
}: {
  readonly session: TibaTraceSessionInfo;
  readonly apiFetch: typeof fetch;
  readonly onLogout: () => Promise<void>;
}) {
  const [workspace, setWorkspace] = useState<'clinical' | 'retail' | 'register' | 'print' | 'sync'>('clinical');
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
  const viewport = useViewport();
  // Below `expanded` the rail cannot hold its 320px and leave the workspace a
  // usable width, so it moves under the workspace instead of beside it. It is
  // still on the page -- a blocking finding must never be a screen away.
  const railBeside = !viewportAtMost(viewport, 'medium');

  useEffect(() => {
    void refreshQueue();
  }, [refreshQueue]);

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
        onWorkspaceChange={setWorkspace}
        onLock={() => setLocked(true)}
        onLogout={onLogout}
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
      ) : <>
      <PatientSafetyBanner patient={patient} />
      <WorkflowRibbon stages={stages} />

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
            <>
              <EpisodeWorkspace
                episode={state.selected}
                gateReason={state.gate.blockedReason}
                onRefresh={() => void refresh()}
              />
              <div style={{ marginTop: spacing.xl }}>
                <PrescriptionWorkspace
                  lines={state.selected.lines}
                  apiFetch={apiFetch}
                  episodeId={state.selected.id}
                  onTransition={() => void refresh()}
                />
              </div>
              <div style={{ marginTop: spacing.xxl }}>
                <EpisodeTimelineSection
                  episodeId={state.selected.id}
                  apiFetch={apiFetch}
                />
              </div>
              <section id="payment-workspace" style={{ marginTop: spacing.xxl }}>
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
              </section>
              <div style={{ marginTop: spacing.xxl }}>
                <CounsellingPanel
                  counsellingStatus={state.selected.counselling_status}
                  busy={state.busy}
                  onRecord={(request) => void recordCounselling(request)}
                />
              </div>
              <section id="collection-workspace" style={{ marginTop: spacing.xxl }}>
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
            </>
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
        onOpenPayment={() => document.getElementById('payment-workspace')?.scrollIntoView({ block: 'start' })}
        onOpenCollection={() => document.getElementById('collection-workspace')?.scrollIntoView({ block: 'start' })}
      />
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
}: {
  readonly busy: boolean;
  readonly operator: string;
  readonly workspace: 'clinical' | 'retail' | 'register' | 'print' | 'sync';
  readonly onWorkspaceChange: (workspace: 'clinical' | 'retail' | 'register' | 'print' | 'sync') => void;
  readonly onLock: () => void;
  readonly onLogout: () => Promise<void>;
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
        {(['clinical', 'retail', 'register', 'print', 'sync'] as const).map((option) => (
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
            currentUser={operator}
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
}: {
  readonly episode: { dispensing_number: string; status: string; payment_state: string };
  readonly gateReason: string;
  readonly onRefresh: () => void;
}) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', flexWrap: 'wrap', gap: spacing.md }}>
        <h2 style={{ fontSize: fontSize.sectionTitle, margin: 0, fontVariantNumeric: 'tabular-nums' }}>
          {episode.dispensing_number}
        </h2>
        <span style={{ color: text.secondary, fontSize: fontSize.caption }}>
          {episode.status.replace(/_/g, ' ')} · payment {episode.payment_state.replace(/_/g, ' ')}
        </span>
        <button
          type="button"
          onClick={onRefresh}
          style={{
            marginLeft: 'auto',
            padding: '8px 12px',
            borderRadius: 8,
            border: `1px solid ${surface.borderStrong}`,
            background: surface.raised,
            cursor: 'pointer',
            minHeight: 36,
          }}
        >
          Refresh
        </button>
      </div>

      {gateReason ? (
        <div style={{ marginTop: spacing.lg }}>
          <BlockingReason status="BLOCKING" reason={gateReason} />
        </div>
      ) : null}
    </div>
  );
}

function ActionBar({
  nextLabel,
  canTakePayment,
  canConfirmCollection,
  onOpenPayment,
  onOpenCollection,
}: {
  readonly nextLabel: string;
  readonly canTakePayment: boolean;
  readonly canConfirmCollection: boolean;
  readonly onOpenPayment: () => void;
  readonly onOpenCollection: () => void;
}) {
  const primary = canTakePayment
    ? { label: 'Review payment', onClick: onOpenPayment }
    : canConfirmCollection
      ? { label: 'Review collection', onClick: onOpenCollection }
      : null;

  return (
    <footer
      style={{
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: spacing.md,
        padding: `${spacing.md}px clamp(${spacing.md}px, 3vw, ${spacing.xl}px)`,
        background: surface.raised,
        borderTop: `1px solid ${surface.border}`,
        // Once the layout stacks, the document scrolls rather than the
        // workspace, and a non-sticky bar would leave the next action at the
        // bottom of a long page.
        position: 'sticky',
        bottom: 0,
        zIndex: 1,
      }}
    >
      <span style={{ fontSize: fontSize.caption, color: text.secondary }}>Next: {nextLabel}</span>
      <div style={{ marginLeft: 'auto', display: 'flex', gap: spacing.sm, flexWrap: 'wrap' }}>
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
