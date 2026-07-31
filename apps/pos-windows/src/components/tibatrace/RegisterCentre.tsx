import {
  PosOperationsClient,
  type CashMovementDTO,
  type PosOperationalRuntimeDTO,
  type ShiftReportDTO,
} from '@dawatrace/shared/operational/index.js';
import { action, autoColumns, fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import { formatDecimal } from '@dawatrace/shared/money.js';
import { useCallback, useEffect, useMemo, useState } from 'react';

const DENOMINATIONS = ['1000', '500', '200', '100', '50', '20', '10', '5', '1'] as const;
const MOVEMENT_KINDS = [
  ['CASH_IN', 'Cash in'],
  ['CASH_OUT', 'Cash out'],
  ['FLOAT_TOP_UP', 'Float top-up'],
  ['SAFE_DROP', 'Safe drop'],
  ['PETTY_CASH', 'Petty cash'],
  ['BANKING', 'Banking'],
  ['CORRECTION', 'Correction'],
  ['OTHER_AUTHORISED_MOVEMENT', 'Other authorised movement'],
] as const;

type RegisterAction =
  | { readonly kind: 'open' }
  | { readonly kind: 'movement' }
  | { readonly kind: 'approve'; readonly movement: CashMovementDTO }
  | { readonly kind: 'x-report' }
  | { readonly kind: 'close' }
  | { readonly kind: 'request-handover' }
  | { readonly kind: 'cancel-handover' }
  | { readonly kind: 'accept-handover'; readonly shiftId: string }
  | { readonly kind: 'view-report'; readonly report: ShiftReportDTO };

export function RegisterCentre({
  apiFetch,
  deviceId,
  initialRuntime = null,
  initialMovements = [],
  initialReports = [],
  autoRefresh = true,
}: {
  readonly apiFetch: typeof fetch;
  readonly deviceId: string;
  readonly initialRuntime?: PosOperationalRuntimeDTO | null;
  readonly initialMovements?: readonly CashMovementDTO[];
  readonly initialReports?: readonly ShiftReportDTO[];
  /** Used only by deterministic visual scenarios; production always refreshes. */
  readonly autoRefresh?: boolean;
}) {
  const client = useMemo(
    () => new PosOperationsClient('/api/pos/shift', { fetcher: apiFetch }),
    [apiFetch],
  );
  const [runtime, setRuntime] = useState<PosOperationalRuntimeDTO | null>(initialRuntime);
  const [movements, setMovements] = useState<readonly CashMovementDTO[]>(initialMovements);
  const [reports, setReports] = useState<readonly ShiftReportDTO[]>(initialReports);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [activeAction, setActiveAction] = useState<RegisterAction | null>(null);

  const refresh = useCallback(async () => {
    if (!deviceId) return;
    setBusy(true);
    try {
      const context = await client.getRuntime(deviceId);
      const [cashMovements, shiftReports] = await Promise.all([
        context.register_session
          ? client.getCashMovements(context.register_session.id)
          : Promise.resolve([]),
        client.getReports(),
      ]);
      setRuntime(context);
      setMovements(cashMovements);
      setReports(
        context.register
          ? shiftReports.filter((report) => report.register_code === context.register?.code)
          : [],
      );
      setError('');
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setBusy(false);
    }
  }, [client, deviceId]);

  useEffect(() => {
    if (autoRefresh) void refresh();
  }, [autoRefresh, refresh]);

  const allowed = new Set(runtime?.allowed_actions ?? []);
  const pendingHandover = runtime?.register_session?.operator_shifts.find(
    (shift) => shift.state === 'HANDOVER_REQUESTED',
  );
  const unapproved = movements.filter((movement) => !movement.approved_at);
  const latestX = reports.find((report) => report.report_type === 'X');
  const latestZ = reports.find((report) => report.report_type === 'Z');

  const complete = async (message: string) => {
    setActiveAction(null);
    setNotice(message);
    await refresh();
  };

  return (
    <main style={root} aria-label="Register Centre">
      <header style={header}>
        <div>
          <p style={eyebrow}>Accountable till operations</p>
          <h1 style={heading}>Register Centre</h1>
          <p style={subheading}>
            Open, count, move and close physical cash against the server-authoritative register session.
          </p>
        </div>
        <button type="button" onClick={() => void refresh()} disabled={busy} style={secondaryButton}>
          {busy ? 'Refreshing…' : 'Refresh register'}
        </button>
      </header>

      {error ? <p role="alert" style={errorText}>{error}</p> : null}
      {notice ? <p role="status" style={noticeText}>{notice}</p> : null}

      <section style={summaryGrid} aria-label="Register summary">
        <Summary label="Register" value={runtime?.register?.code ?? 'Unassigned'} detail={runtime?.register?.name ?? 'Device assignment required'} />
        <Summary label="State" value={runtime?.register?.state ?? 'Unavailable'} detail={runtime?.readiness ?? 'Status unavailable'} />
        <Summary label="Business date" value={runtime?.business_day?.business_date ?? 'Unavailable'} detail={runtime?.business_day?.state ?? 'No open day'} />
        <Summary label="Accountable shift" value={runtime?.operator_shift?.operator_username ?? 'No active operator'} detail={runtime?.operator_shift?.state.replace(/_/g, ' ') ?? 'Action required'} />
      </section>

      {runtime?.notices.length ? (
        <section style={attentionPanel}>
          <strong>Operational attention</strong>
          {runtime.notices.map((item) => <span key={item}>{item}</span>)}
        </section>
      ) : null}

      <section style={sectionCard}>
        <div style={sectionHeader}>
          <div>
            <h2 style={sectionHeading}>Register lifecycle</h2>
            <p style={subheading}>Every consequential action opens a confirmation dialog and refreshes the authoritative state.</p>
          </div>
        </div>
        <div style={actionGrid}>
          <ActionButton
            label="Open register"
            detail="Blind opening-float denomination count"
            disabled={!allowed.has('OPEN_REGISTER') || busy}
            onClick={() => setActiveAction({ kind: 'open' })}
          />
          <ActionButton
            label="Record cash movement"
            detail="Cash in, safe drop, banking or authorised adjustment"
            disabled={!allowed.has('RECORD_CASH_MOVEMENT') || busy}
            onClick={() => setActiveAction({ kind: 'movement' })}
          />
          <ActionButton
            label="Generate X report"
            detail="Interim snapshot; does not close or reset the till"
            disabled={!allowed.has('GENERATE_X_REPORT') || busy}
            onClick={() => setActiveAction({ kind: 'x-report' })}
          />
          <ActionButton
            label="Close with Z report"
            detail="Blind closing count and immutable final report"
            disabled={!allowed.has('CLOSE_REGISTER') || busy || closureHasExternalBlocker(runtime)}
            onClick={() => setActiveAction({ kind: 'close' })}
          />
          <ActionButton
            label={allowed.has('CANCEL_HANDOVER') ? 'Cancel handover' : 'Request handover'}
            detail="Transfer till accountability without closing the register"
            disabled={(!allowed.has('REQUEST_HANDOVER') && !allowed.has('CANCEL_HANDOVER')) || busy}
            onClick={() => setActiveAction({ kind: allowed.has('CANCEL_HANDOVER') ? 'cancel-handover' : 'request-handover' })}
          />
          <ActionButton
            label="Accept handover"
            detail={pendingHandover ? `Take accountability from ${pendingHandover.operator_username}` : 'No handover is awaiting this operator'}
            disabled={!allowed.has('ACCEPT_HANDOVER') || !pendingHandover || busy}
            onClick={() => pendingHandover && setActiveAction({ kind: 'accept-handover', shiftId: pendingHandover.id })}
          />
        </div>
      </section>

      <section style={twoColumn}>
        <div style={sectionCard}>
          <div style={sectionHeader}>
            <div>
              <h2 style={sectionHeading}>Cash movement approvals</h2>
              <p style={subheading}>Creators cannot approve their own movements.</p>
            </div>
            <span style={countChip}>{unapproved.length} pending</span>
          </div>
          {movements.length === 0 ? <Empty message="No cash movements in this session." /> : (
            <div style={list}>
              {movements.slice().reverse().map((movement) => (
                <article key={movement.id} style={listItem}>
                  <div>
                    <strong>{movement.kind.replace(/_/g, ' ')}</strong>
                    <p style={detailText}>{movement.currency} {movement.amount} · {movement.reason_code}</p>
                    <p style={detailText}>Recorded by {movement.created_by_username}{movement.reference ? ` · ${movement.reference}` : ''}</p>
                  </div>
                  {movement.approved_at ? (
                    <span style={approvedChip}>Approved by {movement.approved_by_username}</span>
                  ) : (
                    <button
                      type="button"
                      style={secondaryButton}
                      disabled={!allowed.has('APPROVE_CASH_MOVEMENT') || busy}
                      onClick={() => setActiveAction({ kind: 'approve', movement })}
                    >
                      Review approval
                    </button>
                  )}
                </article>
              ))}
            </div>
          )}
        </div>

        <div style={sectionCard}>
          <div style={sectionHeader}>
            <div>
              <h2 style={sectionHeading}>Immutable reports</h2>
              <p style={subheading}>Snapshots are read as generated; totals are never recalculated in the client.</p>
            </div>
          </div>
          {!latestX && !latestZ ? <Empty message="No X or Z report exists for this register." /> : (
            <div style={list}>
              {latestX ? <ReportRow report={latestX} onOpen={() => setActiveAction({ kind: 'view-report', report: latestX })} /> : null}
              {latestZ ? <ReportRow report={latestZ} onOpen={() => setActiveAction({ kind: 'view-report', report: latestZ })} /> : null}
            </div>
          )}
        </div>
      </section>

      {activeAction ? (
        <RegisterActionModal
          action={activeAction}
          busy={busy}
          runtime={runtime}
          client={client}
          deviceId={deviceId}
          onClose={() => !busy && setActiveAction(null)}
          onError={(message) => setError(message)}
          onBusy={setBusy}
          onComplete={complete}
        />
      ) : null}
    </main>
  );
}

function RegisterActionModal({
  action,
  busy,
  runtime,
  client,
  deviceId,
  onClose,
  onError,
  onBusy,
  onComplete,
}: {
  readonly action: RegisterAction;
  readonly busy: boolean;
  readonly runtime: PosOperationalRuntimeDTO | null;
  readonly client: PosOperationsClient;
  readonly deviceId: string;
  readonly onClose: () => void;
  readonly onError: (message: string) => void;
  readonly onBusy: (busy: boolean) => void;
  readonly onComplete: (message: string) => Promise<void>;
}) {
  const [counts, setCounts] = useState<Record<string, string>>({});
  const [movementKind, setMovementKind] = useState('SAFE_DROP');
  const [amount, setAmount] = useState('');
  const [reasonCode, setReasonCode] = useState('');
  const [description, setDescription] = useState('');
  const [reference, setReference] = useState('');
  const [reason, setReason] = useState('');
  const total = denominationTotal(counts);
  const report = action.kind === 'view-report' ? action.report : null;

  const submit = async () => {
    if (!runtime?.register || busy || report) return;
    onBusy(true);
    onError('');
    try {
      if (action.kind === 'open') {
        await client.openRegister(runtime.register.id, {
          deviceId,
          openingAmount: total,
          denominations: denominationPayload(counts),
        });
        await onComplete(`Register ${runtime.register.code} opened with a confirmed ${runtime.register.currency} ${total} float.`);
      } else if (action.kind === 'movement') {
        await client.recordCashMovement({
          deviceId,
          kind: movementKind,
          amount,
          reasonCode,
          description,
          reference,
        });
        await onComplete('Cash movement recorded. A separate authorised operator must approve it before Z closure.');
      } else if (action.kind === 'approve') {
        await client.approveCashMovement(action.movement.id);
        await onComplete('Cash movement approved with the authenticated supervisor identity.');
      } else if (action.kind === 'x-report') {
        const generated = await client.generateXReport(runtime.register.id, deviceId);
        await onComplete(`X report ${generated.report_number} generated without closing the register.`);
      } else if (action.kind === 'close') {
        const generated = await client.closeRegister(runtime.register.id, {
          deviceId,
          declaredAmount: total,
          denominations: denominationPayload(counts),
          reason,
        });
        await onComplete(`Z report ${generated.report_number} finalised. The register is closed even if printing later fails.`);
      } else if (action.kind === 'request-handover' && runtime.operator_shift) {
        await client.requestHandover(runtime.operator_shift.id, deviceId, reason);
        await onComplete('Handover requested. Lock the workstation and ask the incoming operator to sign in and accept.');
      } else if (action.kind === 'cancel-handover' && runtime.operator_shift) {
        await client.cancelHandover(runtime.operator_shift.id, deviceId);
        await onComplete('The pending handover was cancelled. Accountability remains with this operator.');
      } else if (action.kind === 'accept-handover') {
        await client.acceptHandover(action.shiftId, deviceId);
        await onComplete('Handover accepted. This operator is now accountable for the open register session.');
      }
    } catch (cause) {
      onError(describe(cause));
    } finally {
      onBusy(false);
    }
  };

  const title = actionTitle(action);
  const ready =
    !busy &&
    (action.kind !== 'movement' || (Number(amount) > 0 && reasonCode.trim().length > 0));

  return (
    <div role="presentation" style={modalBackdrop}>
      <section role="dialog" aria-modal="true" aria-labelledby="register-action-title" style={modalCard}>
        <p style={eyebrow}>Governed register action</p>
        <h2 id="register-action-title" style={heading}>{title}</h2>

        {report ? <ReportSnapshot report={report} /> : null}

        {action.kind === 'open' || action.kind === 'close' ? (
          <>
            <p style={subheading}>
              Count the physical drawer by denomination. Expected cash is deliberately hidden until the count is confirmed.
            </p>
            <DenominationEditor counts={counts} currency={runtime?.register?.currency ?? 'KES'} onChange={setCounts} />
            {action.kind === 'close' ? (
              <label style={fieldLabel}>Closing note (optional)
                <textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} style={textarea} />
              </label>
            ) : null}
          </>
        ) : null}

        {action.kind === 'movement' ? (
          <div style={formGrid}>
            <label style={fieldLabel}>Movement type
              <select value={movementKind} onChange={(event) => setMovementKind(event.target.value)} style={input}>
                {MOVEMENT_KINDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label style={fieldLabel}>Amount
              <input inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} style={input} />
            </label>
            <label style={fieldLabel}>Reason code
              <input value={reasonCode} onChange={(event) => setReasonCode(event.target.value)} style={input} placeholder="e.g. SECURITY_THRESHOLD" />
            </label>
            <label style={fieldLabel}>Reference
              <input value={reference} onChange={(event) => setReference(event.target.value)} style={input} />
            </label>
            <label style={{ ...fieldLabel, gridColumn: '1 / -1' }}>Description
              <textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} style={textarea} />
            </label>
          </div>
        ) : null}

        {action.kind === 'approve' ? (
          <Confirmation
            title={`${action.movement.kind.replace(/_/g, ' ')} · ${action.movement.currency} ${action.movement.amount}`}
            detail={`Recorded by ${action.movement.created_by_username} for ${action.movement.reason_code}. Approval confirms a second operator reviewed this movement.`}
          />
        ) : null}
        {action.kind === 'x-report' ? (
          <Confirmation title="Generate interim X report" detail="The report is cumulative from register opening. It does not close the session, reset totals or alter cash." />
        ) : null}
        {action.kind === 'request-handover' ? (
          <label style={fieldLabel}>Handover note (optional)
            <textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} style={textarea} />
          </label>
        ) : null}
        {action.kind === 'cancel-handover' ? (
          <Confirmation title="Cancel pending handover" detail="The current operator remains accountable and the register stays open." />
        ) : null}
        {action.kind === 'accept-handover' ? (
          <Confirmation title="Accept till accountability" detail="The outgoing shift closes and a new accountable shift starts for the signed-in operator. The register session remains open." />
        ) : null}

        <div style={modalActions}>
          <button type="button" disabled={busy} onClick={onClose} style={secondaryButton}>{report ? 'Close' : 'Back'}</button>
          {!report ? (
            <button type="button" disabled={!ready} onClick={() => void submit()} style={primaryButton(ready)}>
              {busy ? 'Working…' : actionConfirmLabel(action)}
            </button>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function DenominationEditor({
  counts,
  currency,
  onChange,
}: {
  readonly counts: Readonly<Record<string, string>>;
  readonly currency: string;
  readonly onChange: (counts: Record<string, string>) => void;
}) {
  return (
    <div style={denominationPanel}>
      <div style={denominationGrid}>
        {DENOMINATIONS.map((face) => (
          <label key={face} style={fieldLabel}>{currency} {face}
            <input
              inputMode="numeric"
              min="0"
              step="1"
              value={counts[face] ?? ''}
              onChange={(event) => onChange({ ...counts, [face]: event.target.value.replace(/[^\d]/g, '') })}
              style={input}
              aria-label={`${currency} ${face} note or coin count`}
            />
          </label>
        ))}
      </div>
      <div style={totalPanel}>
        <span>Counted total</span>
        <strong>{currency} {denominationTotal(counts)}</strong>
      </div>
    </div>
  );
}

function Summary({ label, value, detail }: { readonly label: string; readonly value: string; readonly detail: string }) {
  return <article style={summaryCard}><span style={eyebrow}>{label}</span><strong style={summaryValue}>{value}</strong><span style={detailText}>{detail}</span></article>;
}

function ActionButton({ label, detail, disabled, onClick }: { readonly label: string; readonly detail: string; readonly disabled: boolean; readonly onClick: () => void }) {
  return (
    <button type="button" disabled={disabled} onClick={onClick} style={actionButton(disabled)}>
      <strong>{label}</strong>
      <span>{detail}</span>
    </button>
  );
}

function ReportRow({ report, onOpen }: { readonly report: ShiftReportDTO; readonly onOpen: () => void }) {
  return (
    <article style={listItem}>
      <div>
        <strong>{report.report_type} report · {report.report_number}</strong>
        <p style={detailText}>{formatDate(report.generated_at)} · {report.generated_by_username}</p>
      </div>
      <button type="button" onClick={onOpen} style={secondaryButton}>View snapshot</button>
    </article>
  );
}

function ReportSnapshot({ report }: { readonly report: ShiftReportDTO }) {
  const variance = report.snapshot.variance;
  return (
    <div style={reportPanel}>
      <Confirmation title={`${report.report_type} report ${report.report_number}`} detail={`Generated ${formatDate(report.generated_at)} by ${report.generated_by_username}.`} />
      <dl style={reportGrid}>
        <Detail label="Opening cash" value={`${report.snapshot.currency} ${report.snapshot.cash.opening}`} />
        <Detail label="Cash sales" value={`${report.snapshot.currency} ${report.snapshot.cash.cash_sales}`} />
        <Detail label="Cash in" value={`${report.snapshot.currency} ${report.snapshot.cash.cash_in}`} />
        <Detail label="Cash out" value={`${report.snapshot.currency} ${report.snapshot.cash.cash_out}`} />
        <Detail label="Expected closing" value={`${report.snapshot.currency} ${report.snapshot.cash.expected_closing}`} />
        <Detail label="Grand total" value={`${report.snapshot.currency} ${report.snapshot.tenders.grand_total}`} />
        {variance ? <Detail label="Declared cash" value={`${report.snapshot.currency} ${variance.declared}`} /> : null}
        {variance ? <Detail label="Variance" value={`${report.snapshot.currency} ${variance.difference} · ${variance.classification}`} /> : null}
      </dl>
      {report.exceptions.length ? <p style={errorText}>{report.exceptions.map((item) => item.message).join(' ')}</p> : null}
    </div>
  );
}

function Detail({ label, value }: { readonly label: string; readonly value: string }) {
  return <div><dt style={detailLabel}>{label}</dt><dd style={detailValue}>{value}</dd></div>;
}

function Confirmation({ title, detail }: { readonly title: string; readonly detail: string }) {
  return <div style={confirmation}><strong>{title}</strong><span>{detail}</span></div>;
}

function Empty({ message }: { readonly message: string }) {
  return <p style={empty}>{message}</p>;
}

function denominationPayload(counts: Readonly<Record<string, string>>): Record<string, number> {
  return Object.fromEntries(
    Object.entries(counts)
      .filter(([, count]) => Number(count) > 0)
      .map(([face, count]) => [face, Number(count)]),
  );
}

function denominationTotal(counts: Readonly<Record<string, string>>): string {
  const cents = Object.entries(counts).reduce(
    (sum, [face, count]) => sum + Math.round(Number(face) * 100) * (Number.parseInt(count || '0', 10) || 0),
    0,
  );
  return formatDecimal(cents / 100, 2);
}

function closureHasExternalBlocker(runtime: PosOperationalRuntimeDTO | null): boolean {
  return Boolean(
    runtime?.closure_eligibility.blocking_reasons.some(
      (reason) => !reason.toLowerCase().includes('closing cash declaration'),
    ),
  );
}

function actionTitle(action: RegisterAction): string {
  if (action.kind === 'open') return 'Open register';
  if (action.kind === 'movement') return 'Record cash movement';
  if (action.kind === 'approve') return 'Approve cash movement';
  if (action.kind === 'x-report') return 'Generate X report';
  if (action.kind === 'close') return 'Count and close register';
  if (action.kind === 'request-handover') return 'Request shift handover';
  if (action.kind === 'cancel-handover') return 'Cancel shift handover';
  if (action.kind === 'accept-handover') return 'Accept shift handover';
  return 'Report snapshot';
}

function actionConfirmLabel(action: RegisterAction): string {
  if (action.kind === 'open') return 'Confirm count and open';
  if (action.kind === 'movement') return 'Record movement';
  if (action.kind === 'approve') return 'Approve movement';
  if (action.kind === 'x-report') return 'Generate X report';
  if (action.kind === 'close') return 'Confirm count and close';
  if (action.kind === 'request-handover') return 'Request handover';
  if (action.kind === 'cancel-handover') return 'Cancel handover';
  if (action.kind === 'accept-handover') return 'Accept accountability';
  return 'Confirm';
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Timestamp unavailable' : date.toLocaleString();
}

function describe(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

const root = { minHeight: 0, overflowY: 'auto' as const, padding: spacing.xl, display: 'grid', alignContent: 'start', gap: spacing.lg };
const header = { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: spacing.lg };
const eyebrow = { margin: 0, color: text.secondary, fontSize: fontSize.caption, fontWeight: 700, letterSpacing: 0.5, textTransform: 'uppercase' as const };
const heading = { margin: `${spacing.xs}px 0`, color: text.primary, fontSize: fontSize.screenTitle };
const sectionHeading = { margin: 0, color: text.primary, fontSize: fontSize.sectionTitle };
const subheading = { margin: 0, color: text.secondary, lineHeight: 1.5 };
const detailText = { margin: 0, color: text.secondary, fontSize: fontSize.caption, lineHeight: 1.45 };
const errorText = { margin: 0, padding: spacing.md, borderRadius: 8, background: statusPalette.BLOCKING.surface, color: statusPalette.BLOCKING.foreground };
const noticeText = { margin: 0, padding: spacing.md, borderRadius: 8, background: statusPalette.SAFE.surface, color: statusPalette.SAFE.foreground };
const attentionPanel = { display: 'grid', gap: spacing.xs, padding: spacing.md, border: `1px solid ${statusPalette.ACTION_REQUIRED.border}`, borderRadius: 10, background: statusPalette.ACTION_REQUIRED.surface, color: statusPalette.ACTION_REQUIRED.foreground };
const summaryGrid = { display: 'grid', gridTemplateColumns: autoColumns(180), gap: spacing.md };
const summaryCard = { display: 'grid', gap: spacing.xs, padding: spacing.md, border: `1px solid ${surface.border}`, borderRadius: 10, background: surface.raised };
const summaryValue = { color: text.primary, fontSize: fontSize.bodyLarge };
const sectionCard = { display: 'grid', gap: spacing.md, padding: spacing.lg, border: `1px solid ${surface.border}`, borderRadius: 12, background: surface.raised };
const sectionHeader = { display: 'flex', justifyContent: 'space-between', gap: spacing.md, alignItems: 'flex-start' };
const actionGrid = { display: 'grid', gridTemplateColumns: autoColumns(190), gap: spacing.sm };
const actionButton = (disabled: boolean) => ({ display: 'grid', gap: spacing.xs, minHeight: 82, padding: spacing.md, textAlign: 'left' as const, border: `1px solid ${disabled ? surface.border : action.selectedBorder}`, borderRadius: 10, background: disabled ? surface.sunken : action.selectedSurface, color: disabled ? text.tertiary : text.primary, cursor: disabled ? 'not-allowed' : 'pointer' });
const twoColumn = { display: 'grid', gridTemplateColumns: autoColumns(320), gap: spacing.lg, alignItems: 'start' };
const countChip = { borderRadius: 999, padding: '4px 8px', background: statusPalette.ACTION_REQUIRED.surface, color: statusPalette.ACTION_REQUIRED.foreground, fontSize: fontSize.caption, fontWeight: 700 };
const list = { display: 'grid', gap: spacing.sm };
const listItem = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: spacing.md, padding: spacing.md, border: `1px solid ${surface.border}`, borderRadius: 9, background: surface.page };
const approvedChip = { color: statusPalette.SAFE.foreground, fontSize: fontSize.caption, fontWeight: 700 };
const empty = { margin: 0, padding: spacing.lg, borderRadius: 8, background: surface.page, color: text.secondary, textAlign: 'center' as const };
const secondaryButton = { minHeight: 38, padding: '7px 11px', border: `1px solid ${surface.borderStrong}`, borderRadius: 8, background: surface.raised, color: text.primary, fontWeight: 700, cursor: 'pointer' };
const modalBackdrop = { position: 'fixed' as const, inset: 0, zIndex: 40, display: 'grid', placeItems: 'center', padding: spacing.xl, background: 'rgba(5, 18, 42, 0.56)' };
const modalCard = { width: 'min(760px, 100%)', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' as const, display: 'grid', gap: spacing.md, padding: spacing.xxl, borderRadius: 14, background: surface.raised, boxShadow: '0 22px 60px rgba(0, 0, 0, 0.35)' };
const modalActions = { display: 'flex', justifyContent: 'flex-end', gap: spacing.sm };
const primaryButton = (enabled: boolean) => ({ minHeight: 40, padding: '8px 12px', border: 'none', borderRadius: 8, background: enabled ? action.primary : surface.sunken, color: enabled ? action.primaryForeground : text.tertiary, fontWeight: 700, cursor: enabled ? 'pointer' : 'not-allowed' });
const formGrid = { display: 'grid', gridTemplateColumns: autoColumns(220), gap: spacing.md };
const fieldLabel = { display: 'grid', gap: spacing.xs, color: text.primary, fontSize: fontSize.caption, fontWeight: 700 };
const input = { minHeight: 40, boxSizing: 'border-box' as const, padding: spacing.sm, border: `1px solid ${surface.borderStrong}`, borderRadius: 8, color: text.primary, background: surface.raised, font: 'inherit' };
const textarea = { minHeight: 82, resize: 'vertical' as const, padding: spacing.sm, border: `1px solid ${surface.borderStrong}`, borderRadius: 8, color: text.primary, font: 'inherit' };
const denominationPanel = { display: 'grid', gap: spacing.md };
const denominationGrid = { display: 'grid', gridTemplateColumns: autoColumns(140), gap: spacing.sm };
const totalPanel = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: spacing.md, borderRadius: 8, background: surface.inverse, color: action.primaryForeground };
const confirmation = { display: 'grid', gap: spacing.xs, padding: spacing.md, border: `1px solid ${surface.border}`, borderRadius: 8, background: surface.page, color: text.primary };
const reportPanel = { display: 'grid', gap: spacing.md };
const reportGrid = { display: 'grid', gridTemplateColumns: autoColumns(180), gap: spacing.md, margin: 0 };
const detailLabel = { color: text.secondary, fontSize: fontSize.caption, textTransform: 'uppercase' as const, letterSpacing: 0.4 };
const detailValue = { margin: '3px 0 0', color: text.primary, fontSize: fontSize.body };
