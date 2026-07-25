import { deriveStages, fontFamily, fontSize, nextAction, spacing, surface, text } from '@dawatrace/shared/design-system/index.js';
import { useEffect, useMemo, useState } from 'react';

import { ClinicalRail } from './components/tibatrace/ClinicalRail.js';
import type { ClinicalSummary } from './components/tibatrace/ClinicalRail.js';
import { PatientSafetyBanner } from './components/tibatrace/PatientSafetyBanner.js';
import { PaymentPanel } from './components/tibatrace/PaymentPanel.js';
import { PrescriptionWorkspace } from './components/tibatrace/PrescriptionWorkspace.js';
import type { PatientSummary } from './components/tibatrace/PatientSafetyBanner.js';
import { BlockingReason } from './components/tibatrace/StatusBadge.js';
import { WorkflowRibbon } from './components/tibatrace/WorkflowRibbon.js';
import { usePosWorkflow } from './state/usePosWorkflow.js';

/**
 * TibaTrace Windows clinical operations console.
 *
 * Four persistent regions: header, patient banner, workspace + clinical rail,
 * contextual action bar. The rail is never hidden behind a modal, so what is
 * blocking the operator stays on screen while they work.
 */
export function App() {
  const { state, refreshQueue, select, refresh, takePayment, confirmCollection } = usePosWorkflow();
  const [clinical] = useState<ClinicalSummary | null>(null);

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
        fullName: state.selected.patient,
        reference: state.selected.dispensing_number,
        // Allergy status is unknown until the clinical screening supplies it,
        // and must render as unknown rather than as "none known".
        allergyStatus: 'UNKNOWN',
        badges: [],
        prescriptionRef: state.selected.prescription,
      }
    : null;

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateRows: 'auto auto auto 1fr auto',
        height: '100vh',
        fontFamily: fontFamily.sans,
        background: surface.page,
        color: text.primary,
      }}
    >
      <Header busy={state.busy} />
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
            <>
              <EpisodeWorkspace
                episode={state.selected}
                gateReason={state.gate.blockedReason}
                onRefresh={() => void refresh()}
              />
              <div style={{ marginTop: spacing.xl }}>
                <PrescriptionWorkspace lines={state.selected.lines} />
              </div>
              <div style={{ marginTop: spacing.xxl }}>
                <PaymentPanel
                  paymentState={state.selected.payment_state}
                  amountDue={state.selected.paid_amount}
                  amountSettled={state.selected.paid_amount}
                  canTakePayment={state.gate.canTakePayment}
                  blockedReason={state.gate.canTakePayment ? '' : state.gate.blockedReason}
                  busy={state.busy}
                  onTakePayment={(tender, amount, reference) =>
                    void takePayment(tender, amount, reference)
                  }
                />
              </div>
            </>
          ) : (
            <Queue queue={state.queue} busy={state.busy} onSelect={(id) => void select(id)} />
          )}
        </main>

        <ClinicalRail summary={clinical} />
      </div>

      <ActionBar
        nextLabel={next ? next.label : 'No action available'}
        canTakePayment={state.gate.canTakePayment}
        canConfirmCollection={state.gate.canConfirmCollection}
        onTakePayment={() => void takePayment('CASH', '0.00', '')}
        onConfirmCollection={() => void confirmCollection('', '', 'SELF')}
      />
    </div>
  );
}

function Header({ busy }: { readonly busy: boolean }) {
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
      <strong style={{ fontSize: fontSize.bodyLarge, letterSpacing: 0.3 }}>TibaTrace</strong>
      <span style={{ fontSize: fontSize.caption, opacity: 0.8 }}>Clinical operations console</span>
      <span style={{ marginLeft: 'auto', fontSize: fontSize.caption, opacity: 0.8 }}>
        {busy ? 'Working…' : 'Ready'}
      </span>
    </header>
  );
}

function Queue({
  queue,
  busy,
  onSelect,
}: {
  readonly queue: readonly { id: string; dispensing_number: string; status: string }[];
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
          <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>
            {episode.dispensing_number}
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
  onTakePayment,
  onConfirmCollection,
}: {
  readonly nextLabel: string;
  readonly canTakePayment: boolean;
  readonly canConfirmCollection: boolean;
  readonly onTakePayment: () => void;
  readonly onConfirmCollection: () => void;
}) {
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
        {/* Disabled state is driven by the server-derived gate, never by local
            optimism. A disabled control still cannot be activated by keyboard. */}
        <PrimaryButton disabled={!canTakePayment} onClick={onTakePayment}>
          Take payment
        </PrimaryButton>
        <PrimaryButton disabled={!canConfirmCollection} onClick={onConfirmCollection}>
          Confirm collection
        </PrimaryButton>
      </div>
    </footer>
  );
}

function PrimaryButton({
  disabled,
  onClick,
  children,
}: {
  readonly disabled: boolean;
  readonly onClick: () => void;
  readonly children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      style={{
        padding: '10px 18px',
        borderRadius: 8,
        border: 'none',
        background: disabled ? surface.sunken : '#12854A',
        color: disabled ? text.tertiary : '#fff',
        fontSize: fontSize.body,
        fontWeight: 600,
        cursor: disabled ? 'not-allowed' : 'pointer',
        minHeight: 44,
      }}
    >
      {children}
    </button>
  );
}
