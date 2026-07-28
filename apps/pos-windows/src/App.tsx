import { action, deriveStages, fontFamily, fontSize, nextAction, spacing, surface, text } from '@dawatrace/shared/design-system/index.js';
import { useEffect, useMemo, useState } from 'react';

import { ClinicalRail } from './components/tibatrace/ClinicalRail.js';
import { ClinicalReviewWorkspace, type ClinicalOverrideActionInput } from './components/tibatrace/ClinicalReviewWorkspace.js';
import { CollectionPanel, CounsellingPanel } from './components/tibatrace/CounsellingAndCollection.js';
import { PatientSafetyBanner } from './components/tibatrace/PatientSafetyBanner.js';
import { OperationalStatusBar } from './components/tibatrace/OperationalStatusBar.js';
import { PaymentPanel } from './components/tibatrace/PaymentPanel.js';
import { PrintCentre } from './components/tibatrace/PrintCentre.js';
import { PrescriptionWorkspace } from './components/tibatrace/PrescriptionWorkspace.js';
import { RetailWorkspace } from './components/tibatrace/RetailWorkspace.js';
import { SyncCentre } from './components/tibatrace/SyncCentre.js';
import type { PatientSummary } from './components/tibatrace/PatientSafetyBanner.js';
import { BlockingReason } from './components/tibatrace/StatusBadge.js';
import { WorkflowRibbon } from './components/tibatrace/WorkflowRibbon.js';
import { useClinicalScreening } from './state/useClinicalScreening.js';
import { usePosWorkflow } from './state/usePosWorkflow.js';
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
  const [workspace, setWorkspace] = useState<'clinical' | 'retail' | 'print' | 'sync'>('clinical');
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
        height: '100vh',
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
        onLogout={onLogout}
      />
      <OperationalStatusBar
        apiFetch={apiFetch}
        deviceId={session.deviceId}
      />
      {workspace === 'retail' ? (
        <RetailWorkspace apiFetch={apiFetch} deviceId={session.deviceId} />
      ) : workspace === 'print' ? (
        <PrintCentre apiFetch={apiFetch} deviceId={session.deviceId} />
      ) : workspace === 'sync' ? (
        <SyncCentre apiFetch={apiFetch} deviceId={session.deviceId} journal={journal} onOpenPrint={() => setWorkspace('print')} />
      ) : <>
      <PatientSafetyBanner patient={patient} />
      <WorkflowRibbon stages={stages} />

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 360px', minHeight: 0 }}>
        <main style={{ padding: spacing.xl, overflowY: 'auto' }}>
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
                <PrescriptionWorkspace lines={state.selected.lines} />
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
            <Queue queue={state.queue} busy={state.busy} onSelect={(id) => void select(id)} />
          )}
        </main>

        <div style={{ display: 'flex', flexDirection: 'column' }}>
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
    </div>
  );
}

function Header({
  busy,
  operator,
  workspace,
  onWorkspaceChange,
  onLogout,
}: {
  readonly busy: boolean;
  readonly operator: string;
  readonly workspace: 'clinical' | 'retail' | 'print' | 'sync';
  readonly onWorkspaceChange: (workspace: 'clinical' | 'retail' | 'print' | 'sync') => void;
  readonly onLogout: () => Promise<void>;
}) {
  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: spacing.lg,
        padding: `${spacing.sm}px ${spacing.xl}px`,
        background: surface.inverse,
        color: text.inverse,
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
          <span style={{ fontSize: fontSize.caption, opacity: 0.8 }}>Clinical operations console</span>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 4 }}>
        {(['clinical', 'retail', 'print', 'sync'] as const).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onWorkspaceChange(option)}
            style={{
              minHeight: 34,
              padding: '4px 10px',
              border: '1px solid rgba(255,255,255,0.35)',
              borderRadius: 7,
              background: workspace === option ? '#fff' : 'transparent',
              color: workspace === option ? surface.inverse : '#fff',
              fontWeight: 700,
              cursor: 'pointer',
              textTransform: 'capitalize',
            }}
          >
            {option === 'print' ? 'Print Centre' : option === 'sync' ? 'Sync Centre' : option}
          </button>
        ))}
      </div>
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: spacing.md }}>
        <span style={{ fontSize: fontSize.caption, opacity: 0.8 }}>
          {/* The operator's name, not a truncated primary key. Falls back to
              the id only when the server did not send a username. */}
          {busy ? 'Working…' : operator || 'Signed in'}
        </span>
        <button
          type="button"
          onClick={() => void onLogout()}
          style={{
            minHeight: 36,
            padding: '6px 12px',
            border: '1px solid rgba(255,255,255,0.35)',
            borderRadius: 8,
            background: 'transparent',
            color: '#fff',
            cursor: 'pointer',
          }}
        >
          Sign out
        </button>
      </div>
    </header>
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

  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        padding: spacing.xl,
        boxSizing: 'border-box',
        background: surface.page,
        fontFamily: fontFamily.sans,
        color: text.primary,
      }}
    >
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
          width: 'min(420px, 100%)',
          display: 'grid',
          gap: spacing.md,
          padding: spacing.xxl,
          border: `1px solid ${surface.border}`,
          borderRadius: 16,
          background: surface.raised,
          boxShadow: '0 20px 50px rgba(0, 20, 50, 0.12)',
        }}
      >
        <img
          src="./brand/tibatrace-logo.jpeg"
          alt="TibaTrace — Trace. Trust. Health."
          style={{ width: 180, maxWidth: '100%', margin: '0 auto' }}
        />
        <div>
          <h1 style={{ margin: 0, fontSize: fontSize.screenTitle }}>Windows POS</h1>
          <p style={{ color: text.secondary, marginBottom: 0 }}>
            Sign in with your assigned TibaTrace operator account.
          </p>
        </div>
        {error ? <BlockingReason status="BLOCKING" reason={error} /> : null}
        <label style={{ display: 'grid', gap: spacing.xs, fontSize: fontSize.caption }}>
          Username
          <input
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
            maxLength={150}
            style={{
              minHeight: 44,
              border: `1px solid ${surface.borderStrong}`,
              borderRadius: 8,
              padding: '0 12px',
              fontSize: fontSize.body,
            }}
          />
        </label>
        <label style={{ display: 'grid', gap: spacing.xs, fontSize: fontSize.caption }}>
          Password
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            maxLength={256}
            style={{
              minHeight: 44,
              border: `1px solid ${surface.borderStrong}`,
              borderRadius: 8,
              padding: '0 12px',
              fontSize: fontSize.body,
            }}
          />
        </label>
        <button
          type="submit"
          disabled={busy || !username.trim() || !password}
          style={{
            minHeight: 44,
            border: 'none',
            borderRadius: 8,
            background: busy || !username.trim() || !password ? surface.sunken : '#12854A',
            color: busy || !username.trim() || !password ? text.tertiary : '#fff',
            fontSize: fontSize.body,
            fontWeight: 600,
            cursor: busy || !username.trim() || !password ? 'not-allowed' : 'pointer',
          }}
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  );
}

function Queue({
  queue,
  busy,
  onSelect,
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
}) {
  if (busy && queue.length === 0) {
    return <p style={{ color: text.secondary }}>Loading dispensing queue…</p>;
  }
  if (queue.length === 0) {
    return (
      <div>
        <h2 style={{ fontSize: fontSize.sectionTitle, margin: 0 }}>No prescriptions waiting</h2>
        <p style={{ color: text.secondary }}>Scan or search for a prescription to begin.</p>
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.sm }}>
      {queue.map((episode) => (
        <button
          key={episode.id}
          type="button"
          onClick={() => onSelect(episode.id)}
          style={{
            display: 'flex',
            justifyContent: 'space-between',
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
  );
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
      <div style={{ display: 'flex', alignItems: 'baseline', gap: spacing.md }}>
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
        gap: spacing.md,
        padding: `${spacing.md}px ${spacing.xl}px`,
        background: surface.raised,
        borderTop: `1px solid ${surface.border}`,
      }}
    >
      <span style={{ fontSize: fontSize.caption, color: text.secondary }}>Next: {nextLabel}</span>
      <div style={{ marginLeft: 'auto', display: 'flex', gap: spacing.sm }}>
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
