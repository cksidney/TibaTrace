import type { DurableActionJournal, OfflineAction } from '@dawatrace/shared/dispensing/index.js';
import {
  checkPosClientVersion,
  getCachedPosClientVersion,
  type PosClientVersionStatus,
} from '@dawatrace/shared/operational/index.js';
import { action, autoColumns, fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import { useCallback, useEffect, useState } from 'react';

interface RuntimeStatus {
  readonly readiness: 'READY' | 'ATTENTION' | 'UNASSIGNED';
  readonly notices: readonly string[];
}

interface PrintJobSummary {
  readonly status: string;
}

interface ReconciliationResult {
  readonly applied: boolean;
  readonly authoritative_reference: string;
}

export interface SyncCentreVisualSnapshot {
  readonly entries: readonly OfflineAction[];
  readonly runtime: RuntimeStatus | null;
  readonly clinicalConnected: boolean | null;
  readonly printCounts: { readonly queued: number; readonly retryRequired: number };
  readonly clientVersion?: PosClientVersionStatus | null;
}

function localClientVersion(): string {
  return window.tibatrace?.version ?? '0.0.0';
}

export function SyncCentre({ apiFetch, deviceId, journal, onOpenPrint, initialSnapshot, autoRefresh = true }: {
  readonly apiFetch: typeof fetch;
  readonly deviceId: string;
  readonly journal: DurableActionJournal | null;
  readonly onOpenPrint: () => void;
  /** Used only by deterministic visual scenarios; production always refreshes. */
  readonly initialSnapshot?: SyncCentreVisualSnapshot;
  readonly autoRefresh?: boolean;
}) {
  const [entries, setEntries] = useState<readonly OfflineAction[]>(initialSnapshot?.entries ?? journal?.entries ?? []);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(initialSnapshot?.runtime ?? null);
  const [clinicalConnected, setClinicalConnected] = useState<boolean | null>(initialSnapshot?.clinicalConnected ?? null);
  const [printCounts, setPrintCounts] = useState(initialSnapshot?.printCounts ?? { queued: 0, retryRequired: 0 });
  const [clientVersion, setClientVersion] = useState<PosClientVersionStatus | null>(
    initialSnapshot?.clientVersion ?? getCachedPosClientVersion(),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [entryToReconcile, setEntryToReconcile] = useState<OfflineAction | null>(null);

  const request = useCallback(async (path: string, init?: RequestInit) => {
    const response = await apiFetch(path, {
      ...init,
      headers: {
        Accept: 'application/json',
        'X-POS-Client-Platform': 'WINDOWS',
        'X-POS-Client-Version': localClientVersion(),
        ...(init?.headers ?? {}),
      },
    });
    if (response.ok) return response;
    const payload = (await response.json().catch(() => null)) as { error?: string; detail?: string } | null;
    throw new Error(payload?.error || payload?.detail || `Sync status request failed (${response.status}).`);
  }, [apiFetch]);

  const refresh = useCallback(async () => {
    setBusy(true);
    setError('');
    try {
      const [runtimeResult, clinicalResult, printResult, versionResult] = await Promise.allSettled([
        request(`/api/pos/shift/registers/runtime/?device_id=${encodeURIComponent(deviceId)}`).then(async (response) => response.json() as Promise<RuntimeStatus>),
        request('/api/pos/clinical-screening/ruleset-version/'),
        request(`/api/pos/dispensing/print-jobs/?device_id=${encodeURIComponent(deviceId)}`).then(async (response) => response.json() as Promise<PrintJobSummary[] | { results?: PrintJobSummary[] }>),
        checkPosClientVersion({
          platform: 'WINDOWS',
          version: localClientVersion(),
          fetcher: apiFetch,
        }, { force: true }),
      ]);
      if (runtimeResult.status === 'fulfilled') setRuntime(runtimeResult.value);
      else setRuntime(null);
      setClinicalConnected(clinicalResult.status === 'fulfilled');
      if (printResult.status === 'fulfilled') {
        const jobs = Array.isArray(printResult.value) ? printResult.value : printResult.value.results ?? [];
        setPrintCounts({
          queued: jobs.filter((job) => job.status === 'QUEUED' || job.status === 'RENDERED').length,
          retryRequired: jobs.filter((job) => job.status === 'RETRY_REQUIRED').length,
        });
      } else {
        setPrintCounts({ queued: 0, retryRequired: 0 });
      }
      if (versionResult.status === 'fulfilled') setClientVersion(versionResult.value);
      setEntries(journal?.entries ?? []);
      if (runtimeResult.status === 'rejected' && clinicalResult.status === 'rejected' && printResult.status === 'rejected') {
        throw new Error('No authoritative sync status source is reachable.');
      }
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setBusy(false);
    }
  }, [apiFetch, deviceId, journal, request]);

  useEffect(() => {
    if (autoRefresh) void refresh();
  }, [autoRefresh, refresh]);

  const reconcile = async () => {
    if (!entryToReconcile || !journal) return;
    setBusy(true);
    setError('');
    try {
      const response = await request(`/api/pos/dispensing/episodes/${entryToReconcile.episodeId}/reconcile-action/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_type: entryToReconcile.type, idempotency_key: entryToReconcile.idempotencyKey }),
      });
      const result = (await response.json()) as ReconciliationResult;
      await journal.reconcile(entryToReconcile.id, result.applied);
      setEntries(journal.entries);
      setNotice(result.applied
        ? `Server confirmed the original action (${result.authoritative_reference}).`
        : 'Server found no original action. The journal keeps it pending; only its original workflow may submit it again.');
      setEntryToReconcile(null);
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setBusy(false);
    }
  };

  const unknownEntries = entries.filter((entry) => entry.state === 'NEEDS_RECONCILIATION');
  const pendingEntries = entries.filter((entry) => entry.state === 'PENDING' || entry.state === 'IN_FLIGHT');
  const versionState = clientVersion?.update_required
    ? 'BLOCKING'
    : clientVersion?.update_available
      ? 'ACTION_REQUIRED'
      : clientVersion
        ? 'SAFE'
        : 'ACTION_REQUIRED';
  const versionDetail = !clientVersion
    ? 'Daily HQ alignment check has not completed yet.'
    : clientVersion.update_required
      ? `HQ requires build ${clientVersion.latest_build} (${clientVersion.latest_version}). This till is on ${clientVersion.client_version || `build ${clientVersion.client_build}`}. ${clientVersion.operations_impact || 'Update before continuing dispensing, cash or clinical work.'}`
      : clientVersion.update_available
        ? `HQ published ${clientVersion.latest_version}. ${clientVersion.operations_impact || 'Install the update from HQ till installers when the shift allows.'}`
        : `Aligned with HQ release ${clientVersion.latest_version || clientVersion.client_version}. Rechecks daily.`;

  return (
    <main style={root} aria-label="Sync Centre">
      <header style={header}>
        <div>
          <p style={eyebrow}>Authoritative recovery</p>
          <h1 style={heading}>Sync Centre</h1>
          <p style={subheading}>Refreshes status only. It never blindly replays payment, collection, supply or clinical decisions.</p>
        </div>
        <button type="button" disabled={busy} onClick={() => void refresh()} style={secondaryButton}>{busy ? 'Refreshing…' : 'Refresh status'}</button>
      </header>

      {error ? <p role="alert" style={errorText}>{error}</p> : null}
      {notice ? <p role="status" style={noticeText}>{notice}</p> : null}

      <section style={grid}>
        <StatusCard title="HQ client alignment" state={versionState} detail={versionDetail} />
        <StatusCard title="Clinical authority" state={clinicalConnected === true ? 'SAFE' : clinicalConnected === false ? 'BLOCKING' : 'ACTION_REQUIRED'} detail={clinicalConnected === true ? 'The server clinical ruleset endpoint is reachable. Offline clinical decisions are not replayed from this screen.' : clinicalConnected === false ? 'Clinical authority could not be reached. Dispensing remains fail-closed.' : 'Checking the clinical authority endpoint.'} />
        <StatusCard title="Operational context" state={runtime?.readiness === 'READY' ? 'SAFE' : runtime ? 'ACTION_REQUIRED' : 'BLOCKING'} detail={runtime ? runtime.notices[0] || `Register status: ${runtime.readiness.toLowerCase()}.` : 'Operational context is unavailable.'} />
        <StatusCard title="Printing" state={printCounts.retryRequired > 0 ? 'ACTION_REQUIRED' : 'SAFE'} detail={printCounts.retryRequired > 0 ? `${printCounts.retryRequired} print job${plural(printCounts.retryRequired)} requires a controlled retry.` : `${printCounts.queued} queued or rendered document${plural(printCounts.queued)} on this device.`} actionLabel="Open Print Centre" onAction={onOpenPrint} />
        <StatusCard title="Retail" state="ACTION_REQUIRED" detail="Retail is currently online-only. No offline retail queue is exposed or retried from Sync Centre." />
      </section>

      <section style={journalCard} aria-labelledby="durable-actions-title">
        <div style={journalHeading}><div><p style={eyebrow}>Device journal</p><h2 id="durable-actions-title" style={sectionHeading}>Dispensing and payment recovery</h2></div><span style={countChip}>{entries.length} retained</span></div>
        {!journal && !initialSnapshot ? <p style={subheading}>Secure local journal is unavailable; no local action is assumed complete.</p> : null}
        {unknownEntries.length > 0 ? <p style={warningText}>{unknownEntries.length} consequential action{plural(unknownEntries.length)} need server reconciliation before the affected episode can continue.</p> : null}
        {entries.length === 0 ? <p style={subheading}>No local dispensing, payment or collection action is awaiting recovery.</p> : <div style={entryList}>{entries.map((entry) => <JournalEntry key={entry.id} entry={entry} busy={busy} onReconcile={() => setEntryToReconcile(entry)} />)}</div>}
        {pendingEntries.length > 0 ? <p style={detailText}>Pending items are retained for audit. Sync Centre does not dispatch them; return to their original workflow when the operator is ready.</p> : null}
      </section>

      {entryToReconcile ? <ReconciliationModal entry={entryToReconcile} busy={busy} onClose={() => !busy && setEntryToReconcile(null)} onConfirm={() => void reconcile()} /> : null}
    </main>
  );
}


function StatusCard({ title, state, detail, actionLabel, onAction }: { readonly title: string; readonly state: keyof typeof statusPalette; readonly detail: string; readonly actionLabel?: string; readonly onAction?: () => void }) {
  const palette = statusPalette[state];
  return <section style={{ ...statusCard, borderTopColor: palette.accent }}><p style={eyebrow}>{title}</p><p style={{ ...stateLabel, color: palette.foreground }}>{state === 'SAFE' ? 'Current' : state === 'BLOCKING' ? 'Attention required' : 'Review'}</p><p style={detailText}>{detail}</p>{actionLabel && onAction ? <button type="button" onClick={onAction} style={secondaryButton}>{actionLabel}</button> : null}</section>;
}

function JournalEntry({ entry, busy, onReconcile }: { readonly entry: OfflineAction; readonly busy: boolean; readonly onReconcile: () => void }) {
  const state = entry.state === 'CONFIRMED' ? 'SAFE' : entry.state === 'NEEDS_RECONCILIATION' ? 'BLOCKING' : 'ACTION_REQUIRED';
  const palette = statusPalette[state];
  return <article style={{ ...entryCard, borderLeftColor: palette.accent }}><div style={entryHeader}><div><strong>{entry.type.replace(/_/g, ' ')}</strong><p style={detailText}>Episode {entry.episodeId} · attempt {entry.attempts} · {formatDate(entry.queuedAt)}</p></div><span style={{ ...statusChip, background: palette.surface, color: palette.foreground, borderColor: palette.border }}>{entry.state.replace(/_/g, ' ')}</span></div>{entry.failureReason ? <p style={warningText}>{entry.failureReason}</p> : null}{entry.state === 'NEEDS_RECONCILIATION' ? <button type="button" disabled={busy} onClick={onReconcile} style={secondaryButton}>Query original action</button> : null}</article>;
}

function ReconciliationModal({ entry, busy, onClose, onConfirm }: { readonly entry: OfflineAction; readonly busy: boolean; readonly onClose: () => void; readonly onConfirm: () => void }) {
  return <div role="presentation" style={modalBackdrop}><section role="dialog" aria-modal="true" aria-labelledby="reconciliation-title" style={modalCard}><p style={eyebrow}>Authoritative reconciliation</p><h2 id="reconciliation-title" style={heading}>Query original {entry.type.toLowerCase()} action</h2><p style={subheading}>TibaTrace will query the server using this exact idempotency key. It will not resend, cancel or modify the original action.</p><p style={keyText}>{entry.idempotencyKey}</p><div style={modalActions}><button type="button" disabled={busy} onClick={onClose} style={secondaryButton}>Back</button><button type="button" disabled={busy} onClick={onConfirm} style={primaryButton}>Query server</button></div></section></div>;
}

function plural(count: number): string { return count === 1 ? '' : 's'; }
function formatDate(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? 'Timestamp unavailable' : date.toLocaleString(); }
function describe(cause: unknown): string { return cause instanceof Error ? cause.message : String(cause); }

const root = { minHeight: 0, overflowY: 'auto' as const, padding: spacing.xl, display: 'grid', alignContent: 'start', gap: spacing.lg };
const header = { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: spacing.lg };
const eyebrow = { margin: 0, color: text.secondary, fontSize: fontSize.caption, fontWeight: 700, letterSpacing: 0.5, textTransform: 'uppercase' as const };
const heading = { margin: `${spacing.xs}px 0`, color: text.primary, fontSize: fontSize.screenTitle };
const sectionHeading = { margin: 0, color: text.primary, fontSize: fontSize.sectionTitle };
const subheading = { margin: 0, color: text.secondary, lineHeight: 1.5 };
const errorText = { margin: 0, padding: spacing.md, borderRadius: 8, background: statusPalette.BLOCKING.surface, color: statusPalette.BLOCKING.foreground };
const noticeText = { margin: 0, padding: spacing.md, borderRadius: 8, background: statusPalette.SAFE.surface, color: statusPalette.SAFE.foreground };
const grid = { display: 'grid', gridTemplateColumns: autoColumns(260), gap: spacing.md };
const statusCard = { display: 'grid', gap: spacing.sm, padding: spacing.lg, border: `1px solid ${surface.border}`, borderTopWidth: 4, borderRadius: 12, background: surface.raised };
const stateLabel = { margin: 0, fontSize: fontSize.bodyLarge, fontWeight: 700 };
const journalCard = { display: 'grid', gap: spacing.md, padding: spacing.lg, border: `1px solid ${surface.border}`, borderRadius: 12, background: surface.raised };
const journalHeading = { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: spacing.md };
const countChip = { borderRadius: 999, padding: '4px 8px', background: surface.sunken, color: text.secondary, fontSize: fontSize.caption, fontWeight: 700 };
const warningText = { margin: 0, color: statusPalette.BLOCKING.foreground, fontSize: fontSize.caption, lineHeight: 1.45 };
const detailText = { margin: 0, color: text.secondary, fontSize: fontSize.caption, lineHeight: 1.45 };
const entryList = { display: 'grid', gap: spacing.sm };
const entryCard = { display: 'grid', gap: spacing.sm, padding: spacing.md, border: `1px solid ${surface.border}`, borderLeftWidth: 4, borderRadius: 10, background: surface.page };
const entryHeader = { display: 'flex', justifyContent: 'space-between', gap: spacing.md, alignItems: 'flex-start' };
const statusChip = { display: 'inline-flex', border: '1px solid', borderRadius: 999, padding: '4px 8px', fontSize: fontSize.caption, fontWeight: 700, whiteSpace: 'nowrap' as const };
const secondaryButton = { minHeight: 38, justifySelf: 'start', padding: '7px 11px', border: `1px solid ${surface.borderStrong}`, borderRadius: 8, background: surface.raised, color: text.primary, fontWeight: 700, cursor: 'pointer' };
const modalBackdrop = { position: 'fixed' as const, inset: 0, zIndex: 40, display: 'grid', placeItems: 'center', padding: spacing.xl, background: 'rgba(5, 18, 42, 0.56)' };
const modalCard = { width: 'min(520px, 100%)', display: 'grid', gap: spacing.md, padding: spacing.xxl, borderRadius: 14, background: surface.raised, boxShadow: '0 22px 60px rgba(0, 0, 0, 0.35)' };
const keyText = { margin: 0, padding: spacing.sm, overflowWrap: 'anywhere' as const, borderRadius: 8, background: surface.sunken, color: text.primary, fontFamily: 'monospace', fontSize: fontSize.caption };
const modalActions = { display: 'flex', justifyContent: 'flex-end', gap: spacing.sm };
const primaryButton = { minHeight: 40, padding: '8px 12px', border: 'none', borderRadius: 8, background: action.primary, color: action.primaryForeground, fontWeight: 700, cursor: 'pointer' };
