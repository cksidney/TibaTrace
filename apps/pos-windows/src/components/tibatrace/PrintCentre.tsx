import { fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import { useCallback, useEffect, useState } from 'react';

type PrintStatus = 'QUEUED' | 'RENDERED' | 'SENDING' | 'PRINTED' | 'FAILED' | 'RETRY_REQUIRED' | 'CANCELLED';
type PrintActionKind = 'simulate' | 'retry' | 'reprint' | 'cancel';

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
  const [jobs, setJobs] = useState<readonly PosPrintJob[]>(initialJobs);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [activeAction, setActiveAction] = useState<PrintAction | null>(null);
  const [simulatedOutcome, setSimulatedOutcome] = useState<'success' | 'retryable-failure'>('success');
  const [reason, setReason] = useState('');

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
      if (kind === 'simulate') {
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
          body: JSON.stringify({ reason: reason.trim(), transport: 'SIMULATOR' }),
        });
        setNotice('A separately numbered reprint job is queued for the simulator.');
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

  return (
    <main style={root} aria-label="Print Centre">
      <header style={header}>
        <div>
          <p style={eyebrow}>Durable document queue</p>
          <h1 style={heading}>Print Centre</h1>
          <p style={subheading}>This terminal shows its own branch/device queue. Simulator results validate queue controls only; physical printer certification is still required.</p>
        </div>
        <button type="button" onClick={() => void refresh()} disabled={busy} style={secondaryButton}>
          {busy ? 'Refreshing…' : 'Refresh queue'}
        </button>
      </header>

      <section style={simulatorNotice} aria-label="Simulator scope">
        <strong>Simulator-only mode</strong>
        <span>No Windows spooler, ESC/POS, Bluetooth, network printer, cash drawer or scanner is claimed as operational here.</span>
      </section>

      {error ? <p role="alert" style={errorText}>{error}</p> : null}
      {notice ? <p role="status" style={noticeText}>{notice}</p> : null}

      {jobs.length === 0 && !busy ? (
        <section style={emptyState}>
          <h2 style={sectionHeading}>No print jobs for this device</h2>
          <p style={subheading}>Completed payments create an immutable receipt snapshot and its first queued document job.</p>
        </section>
      ) : (
        <section style={jobList} aria-live="polite">
          {jobs.map((job) => <PrintJobCard key={job.id} job={job} busy={busy} onAction={(kind) => {
            setNotice('');
            setReason('');
            setSimulatedOutcome('success');
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
        onReasonChange={setReason}
        onClose={() => !busy && setActiveAction(null)}
        onConfirm={() => void runAction()}
      /> : null}
    </main>
  );
}

function PrintJobCard({ job, busy, onAction }: { readonly job: PosPrintJob; readonly busy: boolean; readonly onAction: (kind: PrintActionKind) => void }) {
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
        {canSimulate ? <ActionButton label="Run simulator" disabled={busy} onClick={() => onAction('simulate')} /> : null}
        {job.status === 'RETRY_REQUIRED' ? <ActionButton label="Retry existing job" disabled={busy} onClick={() => onAction('retry')} /> : null}
        {job.status === 'PRINTED' ? <ActionButton label="Request reprint" disabled={busy} onClick={() => onAction('reprint')} /> : null}
        {canCancel ? <ActionButton label="Cancel job" disabled={busy} onClick={() => onAction('cancel')} /> : null}
      </div>
    </article>
  );
}

function ActionModal({ action, busy, simulatedOutcome, reason, onOutcomeChange, onReasonChange, onClose, onConfirm }: {
  readonly action: PrintAction;
  readonly busy: boolean;
  readonly simulatedOutcome: 'success' | 'retryable-failure';
  readonly reason: string;
  readonly onOutcomeChange: (value: 'success' | 'retryable-failure') => void;
  readonly onReasonChange: (value: string) => void;
  readonly onClose: () => void;
  readonly onConfirm: () => void;
}) {
  const requiresReason = action.kind === 'reprint' || action.kind === 'cancel';
  const title = action.kind === 'simulate'
    ? 'Run deterministic simulator'
    : action.kind === 'retry'
      ? 'Retry existing print job'
      : action.kind === 'reprint'
        ? 'Request reprint'
        : 'Cancel queued print job';
  const confirmLabel = action.kind === 'simulate'
    ? 'Run simulator'
    : action.kind === 'retry'
      ? 'Return job to queue'
      : action.kind === 'reprint'
        ? 'Queue reprint'
        : 'Cancel job';
  const ready = !busy && (!requiresReason || reason.trim().length > 0);
  return (
    <div role="presentation" style={modalBackdrop}>
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
const detailsGrid = { display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: spacing.md, margin: 0 };
const detailLabel = { color: text.secondary, fontSize: fontSize.caption, textTransform: 'uppercase' as const, letterSpacing: 0.4 };
const detailValue = { margin: '3px 0 0', color: text.primary, fontSize: fontSize.body, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const };
const detailText = { margin: 0, color: text.secondary, fontSize: fontSize.caption, lineHeight: 1.45 };
const failureText = { margin: 0, color: statusPalette.BLOCKING.foreground, fontSize: fontSize.caption, lineHeight: 1.45 };
const actions = { display: 'flex', flexWrap: 'wrap' as const, gap: spacing.sm };
const secondaryButton = { minHeight: 38, padding: '7px 11px', border: `1px solid ${surface.borderStrong}`, borderRadius: 8, background: surface.raised, color: text.primary, fontWeight: 700, cursor: 'pointer' };
const modalBackdrop = { position: 'fixed' as const, inset: 0, zIndex: 40, display: 'grid', placeItems: 'center', padding: spacing.xl, background: 'rgba(5, 18, 42, 0.56)' };
const modalCard = { width: 'min(580px, 100%)', display: 'grid', gap: spacing.md, padding: spacing.xxl, borderRadius: 14, background: surface.raised, boxShadow: '0 22px 60px rgba(0, 0, 0, 0.35)' };
const choiceGroup = { display: 'grid', gap: spacing.sm, margin: 0, padding: spacing.md, border: `1px solid ${surface.border}`, borderRadius: 8 };
const fieldLabel = { display: 'grid', gap: spacing.xs, color: text.primary, fontSize: fontSize.caption, fontWeight: 700 };
const radioLabel = { display: 'flex', gap: spacing.sm, alignItems: 'center', color: text.primary, fontSize: fontSize.body };
const textarea = { minHeight: 90, resize: 'vertical' as const, padding: spacing.sm, border: `1px solid ${surface.borderStrong}`, borderRadius: 8, color: text.primary, font: 'inherit' };
const modalActions = { display: 'flex', justifyContent: 'flex-end', gap: spacing.sm };
const primaryButton = (enabled: boolean) => ({ minHeight: 40, padding: '8px 12px', border: 'none', borderRadius: 8, background: enabled ? '#12854A' : surface.sunken, color: enabled ? '#fff' : text.tertiary, fontWeight: 700, cursor: enabled ? 'pointer' : 'not-allowed' });
