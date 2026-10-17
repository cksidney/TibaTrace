import { action, autoColumns, fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import { PosIcon } from './PosIcon.js';
import { useCallback, useEffect, useState } from 'react';

type PrintStatus = 'QUEUED' | 'RENDERED' | 'SENDING' | 'PRINTED' | 'FAILED' | 'RETRY_REQUIRED' | 'CANCELLED';
type PrintActionKind = 'print' | 'confirm' | 'simulate' | 'retry' | 'reprint' | 'cancel';

export interface PosPrintJob {
  readonly id: string;
  readonly document_number: string;
  readonly document_type: string;
  readonly printer: string;
  readonly transport: string;
  readonly status: PrintStatus;
  readonly copy_classification: 'ORIGINAL' | 'REPRINT';
  readonly copy_number: number;
  readonly reprint_reason: string;
  readonly requested_at: string;
  readonly attempt_count: number;
  readonly failure_code: string;
  readonly failure_message: string;
  readonly printed_at: string | null;
  readonly cancellation_reason: string;
}

interface PrintAction {
  readonly kind: PrintActionKind;
  readonly job: PosPrintJob;
}

export function PrintCentre({ apiFetch, deviceId, initialJobs = [], autoRefresh = true }: {
  readonly apiFetch: typeof fetch;
  readonly deviceId: string;
  readonly initialJobs?: readonly PosPrintJob[];
  /** Used only by deterministic visual scenarios; production always refreshes. */
  readonly autoRefresh?: boolean;
}) {
  const [filter, setFilter] = useState<'all' | 'pending' | 'attention' | 'printed'>('all');
  const [setupOpen, setSetupOpen] = useState(false);
  const [jobs, setJobs] = useState<readonly PosPrintJob[]>(initialJobs);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [activeAction, setActiveAction] = useState<PrintAction | null>(null);
  const [simulatedOutcome, setSimulatedOutcome] = useState<'success' | 'retryable-failure'>('success');
  const [reason, setReason] = useState('');
  const [printers, setPrinters] = useState<readonly { name: string; displayName: string }[]>([]);
  const [printer, setPrinter] = useState('');
  const [physicalConfirmed, setPhysicalConfirmed] = useState(false);
  const physicalAvailable = !!window.tibatrace?.print;
  useEffect(() => {
    if (physicalAvailable) void window.tibatrace!.print.printers().then(setPrinters).catch(cause => setError(describe(cause)));
  }, [physicalAvailable]);

  const request = useCallback(async (path: string, init?: RequestInit) => {
    const response = await apiFetch(path, {
      ...init,
      headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
    });
    if (response.ok) return response;
    const payload = (await response.json().catch(() => null)) as { error?: string; detail?: string } | null;
    throw new Error(payload?.error || payload?.detail || `Print service refused the action (${response.status}).`);
  }, [apiFetch]);

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const response = await request(`/api/pos/dispensing/print-jobs/?device_id=${encodeURIComponent(deviceId)}`);
      const payload = (await response.json()) as PosPrintJob[] | { results?: PosPrintJob[] };
      setJobs(Array.isArray(payload) ? payload : payload.results ?? []);
      setError('');
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setBusy(false);
    }
  }, [deviceId, request]);

  useEffect(() => {
    if (autoRefresh) void refresh();
  }, [autoRefresh, refresh]);

  const runAction = async () => {
    if (!activeAction) return;
    const { job, kind } = activeAction;
    if ((kind === 'reprint' || kind === 'cancel') && !reason.trim()) return;
    setBusy(true);
    setError('');
    try {
      if (kind === 'print') {
        if (!printer || !window.tibatrace?.print) throw new Error('Select an installed Windows printer.');
        const result = await window.tibatrace.print.document(job.id, printer);
        setNotice(result.message);
      } else if (kind === 'confirm') {
        if (!physicalConfirmed) throw new Error('Inspect the physical paper and explicitly confirm the outcome.');
        await request(`/api/pos/dispensing/print-jobs/${job.id}/result/`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(simulatedOutcome === 'success' ? { succeeded: true } : {
            succeeded: false, failure_code: 'PHYSICAL_OUTPUT_NOT_CONFIRMED',
            failure_message: 'Operator could not confirm a correct physical copy. Inspect paper/printer before retrying.',
          }),
        });
        setNotice('Physical output outcome recorded. Payment and stock facts are unchanged.');
      } else if (kind === 'simulate') {
        await request(`/api/pos/dispensing/print-jobs/${job.id}/render/`, { method: 'POST' });
        await request(`/api/pos/dispensing/print-jobs/${job.id}/start/`, { method: 'POST' });
        await request(`/api/pos/dispensing/print-jobs/${job.id}/result/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(
            simulatedOutcome === 'success'
              ? { succeeded: true }
              : {
                  succeeded: false,
                  failure_code: 'SIMULATED_TRANSPORT_FAILURE',
                  failure_message: 'Deterministic simulator recorded a retryable transport failure.',
                  retryable: true,
                },
          ),
        });
        setNotice(simulatedOutcome === 'success'
          ? 'Simulator confirmed the document lifecycle. No physical printer was used.'
          : 'Simulator recorded a retry-required job. Settlement remains unchanged.');
      } else if (kind === 'retry') {
        await request(`/api/pos/dispensing/print-jobs/${job.id}/retry/`, { method: 'POST' });
        setNotice('The existing job has returned to the durable queue.');
      } else if (kind === 'reprint') {
        await request(`/api/pos/dispensing/print-jobs/${job.id}/reprint/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: reason.trim(), transport: physicalAvailable ? 'WINDOWS_SPOOLER' : 'SIMULATOR', printer }),
        });
        setNotice('A separately numbered reprint job is queued. The original document is unchanged.');
      } else {
        await request(`/api/pos/dispensing/print-jobs/${job.id}/cancel/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: reason.trim() }),
        });
        setNotice('The queued document was cancelled with its stated reason.');
      }
      setActiveAction(null);
      setReason('');
      await refresh();
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setBusy(false);
    }
  };

  const pending = jobs.filter((job) => ['QUEUED', 'RENDERED', 'SENDING'].includes(job.status));
  const attention = jobs.filter((job) => ['FAILED', 'RETRY_REQUIRED'].includes(job.status));
  const printed = jobs.filter((job) => job.status === 'PRINTED');
  const shown = filter === 'pending' ? pending : filter === 'attention' ? attention : filter === 'printed' ? printed : jobs;
  return (
    <main className="pos-print" style={root} aria-label="Print Centre">
      <header className="pos-page-heading" style={header}>
        <div>
          <p style={eyebrow}>Durable document queue</p>
          <h1 style={heading}>Print Centre</h1>
          <p style={subheading}>Receipts and labels for this terminal, with every print attempt accounted for.</p>
        </div>
        <button type="button" onClick={() => void refresh()} disabled={busy} style={secondaryButton}>
          {busy ? 'Refreshing…' : 'Refresh queue'}
        </button>
      </header>

      <section className="pos-print-connection"><span className="pos-empty-icon"><PosIcon name="print" size={24} /></span><div><strong>{physicalAvailable ? 'Windows printer' : 'Preview environment'}</strong><p>{physicalAvailable ? 'Choose an installed printer for this terminal.' : 'Simulator only. No physical printer is connected.'}</p></div>{physicalAvailable && <label className="pos-printer-picker"><span className="sr-only">Installed USB / Windows printer</span><select value={printer} onChange={event => setPrinter(event.target.value)} disabled={busy}><option value="">Choose an installed printer</option>{printers.map(item => <option key={item.name} value={item.name}>{item.displayName || item.name}</option>)}</select></label>}<button className="pos-button" type="button" aria-expanded={setupOpen} onClick={() => setSetupOpen((value) => !value)}>Printer setup</button></section>
      {setupOpen && <section style={simulatorNotice} aria-label="Simulator scope"><strong>{physicalAvailable ? 'Windows printer driver' : 'Simulator-only mode'}</strong><span>{physicalAvailable ? 'Install the printer’s Windows driver, select its paper size, then print and inspect a test copy. Spooler acceptance does not confirm physical output.' : 'Simulator results check the queue lifecycle only. Use the installed Windows till for physical printing.'}</span>{physicalAvailable && printers.length === 0 && <span>No installed printer found. Install the Windows driver, then reopen Print Centre.</span>}</section>}
      <div className="pos-print-filters" role="group" aria-label="Filter print jobs">{([{id:'all',label:'All documents',count:jobs.length},{id:'pending',label:'In queue',count:pending.length},{id:'attention',label:'Need attention',count:attention.length},{id:'printed',label:'Printed',count:printed.length}] as const).map((item)=><button key={item.id} type="button" aria-pressed={filter===item.id} onClick={()=>setFilter(item.id)}>{item.label}<b>{item.count}</b></button>)}</div>

      {error ? <p role="alert" style={errorText}>{error}</p> : null}
      {notice ? <p role="status" style={noticeText}>{notice}</p> : null}

      {shown.length === 0 && !busy ? (
        <section className="pos-empty-state" style={emptyState}><span className="pos-empty-icon"><PosIcon name="print" size={32} /></span>
          <h2 style={sectionHeading}>{jobs.length ? 'No documents in this view' : 'Your print queue is clear'}</h2>
          <p style={subheading}>Receipts and labels appear here when they are created. A confirmed payment stays recorded if printing needs a retry.</p>
        </section>
      ) : (
        <section style={jobList} aria-live="polite">
          {shown.map((job) => <PrintJobCard key={job.id} job={job} busy={busy} physicalReady={physicalAvailable && !!printer} onAction={(kind) => {
            setNotice('');
            setReason('');
            setSimulatedOutcome('success');
            setPhysicalConfirmed(false);
            setActiveAction({ kind, job });
          }} />)}
        </section>
      )}

      {activeAction ? <ActionModal
        action={activeAction}
        busy={busy}
        simulatedOutcome={simulatedOutcome}
        reason={reason}
        onOutcomeChange={setSimulatedOutcome}
        physicalConfirmed={physicalConfirmed}
        onPhysicalConfirmed={setPhysicalConfirmed}
        onReasonChange={setReason}
        onClose={() => !busy && setActiveAction(null)}
        onConfirm={() => void runAction()}
      /> : null}
    </main>
  );
}

function PrintJobCard({ job, busy, physicalReady, onAction }: { readonly job: PosPrintJob; readonly busy: boolean; readonly physicalReady: boolean; readonly onAction: (kind: PrintActionKind) => void }) {
  const palette = statusPalette[statusPaletteKey(job.status)];
  const canSimulate = job.status === 'QUEUED' || job.status === 'RENDERED';
  const canCancel = job.status === 'QUEUED' || job.status === 'RENDERED';
  return (
    <article style={{ ...jobCard, borderLeftColor: palette.accent }}>
      <div style={jobHeading}>
        <div>
          <p style={eyebrow}>{job.document_type.replace(/_/g, ' ').toLowerCase()}</p>
          <h2 style={sectionHeading}>{job.document_number}</h2>
          <p style={subheading}>Copy {job.copy_number} · {job.copy_classification.toLowerCase()} · {formatDate(job.requested_at)}</p>
        </div>
        <span style={{ ...statusChip, background: palette.surface, color: palette.foreground, borderColor: palette.border }}>{job.status.replace(/_/g, ' ')}</span>
      </div>
      <dl style={detailsGrid}>
        <Detail label="Transport" value={job.transport === 'SIMULATOR' ? 'Deterministic simulator' : job.transport.replace(/_/g, ' ')} />
        <Detail label="Attempts" value={String(job.attempt_count)} />
        <Detail label="Printer" value={job.printer || 'Simulator target'} />
        <Detail label="Printed" value={job.printed_at ? formatDate(job.printed_at) : 'Not confirmed'} />
      </dl>
      {job.failure_message ? <p style={failureText}>{job.failure_code ? `${job.failure_code}: ` : ''}{job.failure_message}</p> : null}
      {job.reprint_reason ? <p style={detailText}>Reprint reason: {job.reprint_reason}</p> : null}
      {job.cancellation_reason ? <p style={detailText}>Cancellation reason: {job.cancellation_reason}</p> : null}
      <div style={actions}>
        {canSimulate ? <ActionButton label="Print via Windows driver" disabled={busy || !physicalReady} onClick={() => onAction('print')} /> : null}
        {job.status === 'SENDING' && job.transport === 'WINDOWS_SPOOLER' ? <ActionButton label="Confirm physical output" disabled={busy} onClick={() => onAction('confirm')} /> : null}
        {canSimulate && job.transport === 'SIMULATOR' ? <ActionButton label="Run simulator" disabled={busy} onClick={() => onAction('simulate')} /> : null}
        {job.status === 'RETRY_REQUIRED' ? <ActionButton label="Retry existing job" disabled={busy} onClick={() => onAction('retry')} /> : null}
        {job.status === 'PRINTED' ? <ActionButton label="Request reprint" disabled={busy} onClick={() => onAction('reprint')} /> : null}
        {canCancel ? <ActionButton label="Cancel job" disabled={busy} onClick={() => onAction('cancel')} /> : null}
      </div>
    </article>
  );
}

function ActionModal({ action, busy, simulatedOutcome, reason, physicalConfirmed, onPhysicalConfirmed, onOutcomeChange, onReasonChange, onClose, onConfirm }: {
  readonly action: PrintAction;
  readonly busy: boolean;
  readonly simulatedOutcome: 'success' | 'retryable-failure';
  readonly reason: string;
  readonly physicalConfirmed: boolean;
  readonly onPhysicalConfirmed: (value: boolean) => void;
  readonly onOutcomeChange: (value: 'success' | 'retryable-failure') => void;
  readonly onReasonChange: (value: string) => void;
  readonly onClose: () => void;
  readonly onConfirm: () => void;
}) {
  const requiresReason = action.kind === 'reprint' || action.kind === 'cancel';
  const title = action.kind === 'print' ? 'Send this copy to the selected Windows printer' : action.kind === 'confirm' ? 'Confirm physical paper output' : action.kind === 'simulate'
    ? 'Run deterministic simulator'
    : action.kind === 'retry'
      ? 'Retry existing print job'
      : action.kind === 'reprint'
        ? 'Request reprint'
        : 'Cancel queued print job';
  const confirmLabel = action.kind === 'print' ? 'Send to printer' : action.kind === 'confirm' ? 'Record physical outcome' : action.kind === 'simulate'
    ? 'Run simulator'
    : action.kind === 'retry'
      ? 'Return job to queue'
      : action.kind === 'reprint'
        ? 'Queue reprint'
        : 'Cancel job';
  const ready = !busy && (!requiresReason || reason.trim().length > 0) && (action.kind !== 'confirm' || physicalConfirmed);
  return (
    <div role="presentation" onClick={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }} style={modalBackdrop}>
      <section role="dialog" aria-modal="true" aria-labelledby="print-action-title" style={modalCard}>
        <p style={eyebrow}>Controlled document action</p>
        <h2 id="print-action-title" style={heading}>{title}</h2>
        <p style={subheading}>Document {action.job.document_number}, copy {action.job.copy_number}. The immutable document snapshot will not change.</p>
        {action.kind === 'simulate' ? <fieldset style={choiceGroup}>
          <legend style={fieldLabel}>Simulator outcome</legend>
          <label style={radioLabel}><input type="radio" checked={simulatedOutcome === 'success'} onChange={() => onOutcomeChange('success')} /> Confirm document printed in simulator</label>
          <label style={radioLabel}><input type="radio" checked={simulatedOutcome === 'retryable-failure'} onChange={() => onOutcomeChange('retryable-failure')} /> Record retryable simulator failure</label>
          <p style={detailText}>No physical printer receives this document.</p>
        </fieldset> : null}
        {action.kind === 'print' ? <p style={detailText}>Send one copy only. If the outcome is unknown, inspect the printer and refresh the queue before retrying. Printer-driver drawer settings may open the connected cash drawer.</p> : null}
        {action.kind === 'confirm' ? <fieldset style={choiceGroup}>
          <legend>Inspect the actual paper copy</legend>
          <label><input type="radio" checked={simulatedOutcome === 'success'} onChange={() => onOutcomeChange('success')} /> I confirm this document and copy printed correctly</label>
          <label><input type="radio" checked={simulatedOutcome === 'retryable-failure'} onChange={() => onOutcomeChange('retryable-failure')} /> No correct physical copy; inspect printer before retrying</label>
          <label><input type="checkbox" checked={physicalConfirmed} onChange={event => onPhysicalConfirmed(event.target.checked)} /> I inspected the printer and confirm the selected outcome</label>
        </fieldset> : null}
        {action.kind === 'retry' ? <p style={detailText}>Retry retains the same job and document identity; it does not create another receipt.</p> : null}
        {requiresReason ? <label style={fieldLabel}>{action.kind === 'reprint' ? 'Reprint reason (required)' : 'Cancellation reason (required)'}
          <textarea value={reason} onChange={(event) => onReasonChange(event.target.value)} rows={4} style={textarea} autoFocus />
        </label> : null}
        <div style={modalActions}>
          <button type="button" disabled={busy} onClick={onClose} style={secondaryButton}>Back</button>
          <button type="button" disabled={!ready} onClick={onConfirm} style={primaryButton(ready)}>{busy ? 'Working…' : confirmLabel}</button>
        </div>
      </section>
    </div>
  );
}

function Detail({ label, value }: { readonly label: string; readonly value: string }) {
  return <div><dt style={detailLabel}>{label}</dt><dd style={detailValue}>{value}</dd></div>;
}

function ActionButton({ label, disabled, onClick }: { readonly label: string; readonly disabled: boolean; readonly onClick: () => void }) {
  return <button type="button" disabled={disabled} onClick={onClick} style={secondaryButton}>{label}</button>;
}

function statusPaletteKey(status: PrintStatus): keyof typeof statusPalette {
  if (status === 'PRINTED') return 'SAFE';
  if (status === 'RETRY_REQUIRED' || status === 'FAILED' || status === 'CANCELLED') return 'BLOCKING';
  return 'ACTION_REQUIRED';
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
const simulatorNotice = { display: 'grid', gap: spacing.xs, padding: spacing.md, border: `1px solid ${statusPalette.ACTION_REQUIRED.border}`, borderRadius: 10, background: statusPalette.ACTION_REQUIRED.surface, color: statusPalette.ACTION_REQUIRED.foreground };
const errorText = { margin: 0, padding: spacing.md, borderRadius: 8, background: statusPalette.BLOCKING.surface, color: statusPalette.BLOCKING.foreground };
const noticeText = { margin: 0, padding: spacing.md, borderRadius: 8, background: statusPalette.SAFE.surface, color: statusPalette.SAFE.foreground };
const emptyState = { padding: spacing.xxl, border: `1px solid ${surface.border}`, borderRadius: 12, background: surface.raised, textAlign: 'center' as const, display: 'grid', gap: spacing.sm };
const jobList = { display: 'grid', gap: spacing.md };
const jobCard = { display: 'grid', gap: spacing.md, padding: spacing.lg, border: `1px solid ${surface.border}`, borderLeftWidth: 5, borderRadius: 12, background: surface.raised };
const jobHeading = { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: spacing.md };
const statusChip = { display: 'inline-flex', alignItems: 'center', border: '1px solid', borderRadius: 999, padding: '4px 8px', fontSize: fontSize.caption, fontWeight: 700, whiteSpace: 'nowrap' as const };
const detailsGrid = { display: 'grid', gridTemplateColumns: autoColumns(180), gap: spacing.md, margin: 0 };
const detailLabel = { color: text.secondary, fontSize: fontSize.caption, textTransform: 'uppercase' as const, letterSpacing: 0.4 };
const detailValue = { margin: '3px 0 0', color: text.primary, fontSize: fontSize.body, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const };
const detailText = { margin: 0, color: text.secondary, fontSize: fontSize.caption, lineHeight: 1.45 };
const failureText = { margin: 0, color: statusPalette.BLOCKING.foreground, fontSize: fontSize.caption, lineHeight: 1.45 };
const actions = { display: 'flex', flexWrap: 'wrap' as const, gap: spacing.sm };
const secondaryButton = { minHeight: 38, padding: '7px 11px', border: `1px solid ${surface.borderStrong}`, borderRadius: 8, background: surface.raised, color: text.primary, fontWeight: 700, cursor: 'pointer' };
const modalBackdrop = { position: 'fixed' as const, inset: 0, zIndex: 40, display: 'grid', placeItems: 'center', padding: spacing.xl, background: 'rgba(5, 18, 42, 0.68)', backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)' };
const modalCard = { width: 'min(580px, 100%)', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' as const, display: 'grid', gap: spacing.md, padding: spacing.xxl, borderRadius: 16, background: surface.raised, boxShadow: '0 28px 75px rgba(0, 0, 0, 0.45), 0 0 0 1px rgba(255, 255, 255, 0.08)' };
const choiceGroup = { display: 'grid', gap: spacing.sm, margin: 0, padding: spacing.md, border: `1px solid ${surface.border}`, borderRadius: 8 };
const fieldLabel = { display: 'grid', gap: spacing.xs, color: text.primary, fontSize: fontSize.caption, fontWeight: 700 };
const radioLabel = { display: 'flex', gap: spacing.sm, alignItems: 'center', color: text.primary, fontSize: fontSize.body };
const textarea = { minHeight: 90, resize: 'vertical' as const, padding: spacing.sm, border: `1px solid ${surface.borderStrong}`, borderRadius: 8, color: text.primary, font: 'inherit' };
const modalActions = { display: 'flex', justifyContent: 'flex-end', gap: spacing.sm };
const primaryButton = (enabled: boolean) => ({ minHeight: 40, padding: '8px 12px', border: 'none', borderRadius: 8, background: enabled ? action.primary : surface.sunken, color: enabled ? action.primaryForeground : text.tertiary, fontWeight: 700, cursor: enabled ? 'pointer' : 'not-allowed' });
