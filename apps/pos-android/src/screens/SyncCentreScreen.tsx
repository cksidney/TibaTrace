import type { DurableActionJournal, OfflineAction } from '@dawatrace/shared/dispensing/index.js';
import {
  checkPosClientVersion,
  getCachedPosClientVersion,
  type PosClientVersionStatus,
} from '@dawatrace/shared/operational/index.js';
import { action, fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { readableColumn } from '../components/tibatrace/layout';
import { createAndroidPosRuntime } from '../native/runtime';

interface RuntimeStatus { readonly readiness: 'READY' | 'ATTENTION' | 'UNASSIGNED'; readonly notices: readonly string[]; }
interface PrintJobSummary { readonly status: string; }
interface ReconciliationResult { readonly applied: boolean; readonly authoritative_reference: string; }

const androidVersion = createAndroidPosRuntime().version;

export function SyncCentreScreen({ apiFetch, deviceId, journal, onOpenPrint }: {
  readonly apiFetch: typeof fetch;
  readonly deviceId: string;
  readonly journal: DurableActionJournal | null;
  readonly onOpenPrint: () => void;
}) {
  const [entries, setEntries] = useState<readonly OfflineAction[]>(journal?.entries ?? []);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [clinicalConnected, setClinicalConnected] = useState<boolean | null>(null);
  const [printCounts, setPrintCounts] = useState({ queued: 0, retryRequired: 0 });
  const [clientVersion, setClientVersion] = useState<PosClientVersionStatus | null>(getCachedPosClientVersion());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [entryToReconcile, setEntryToReconcile] = useState<OfflineAction | null>(null);

  const request = useCallback(async (path: string, init?: RequestInit) => {
    const response = await apiFetch(path, {
      ...init,
      headers: {
        Accept: 'application/json',
        'X-POS-Client-Platform': 'ANDROID',
        'X-POS-Client-Version': androidVersion,
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
        checkPosClientVersion({ platform: 'ANDROID', version: androidVersion, fetcher: apiFetch }, { force: true }),
      ]);
      setRuntime(runtimeResult.status === 'fulfilled' ? runtimeResult.value : null);
      setClinicalConnected(clinicalResult.status === 'fulfilled');
      if (printResult.status === 'fulfilled') {
        const jobs = Array.isArray(printResult.value) ? printResult.value : printResult.value.results ?? [];
        setPrintCounts({ queued: jobs.filter((job) => job.status === 'QUEUED' || job.status === 'RENDERED').length, retryRequired: jobs.filter((job) => job.status === 'RETRY_REQUIRED').length });
      } else setPrintCounts({ queued: 0, retryRequired: 0 });
      if (versionResult.status === 'fulfilled') setClientVersion(versionResult.value);
      setEntries(journal?.entries ?? []);
      if (runtimeResult.status === 'rejected' && clinicalResult.status === 'rejected' && printResult.status === 'rejected') throw new Error('No authoritative sync status source is reachable.');
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setBusy(false);
    }
  }, [apiFetch, deviceId, journal, request]);

  useEffect(() => { void refresh(); }, [refresh]);

  const reconcile = async () => {
    if (!entryToReconcile || !journal) return;
    setBusy(true);
    setError('');
    try {
      const response = await request(`/api/pos/dispensing/episodes/${entryToReconcile.episodeId}/reconcile-action/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action_type: entryToReconcile.type, idempotency_key: entryToReconcile.idempotencyKey }),
      });
      const result = (await response.json()) as ReconciliationResult;
      await journal.reconcile(entryToReconcile.id, result.applied);
      setEntries(journal.entries);
      setNotice(result.applied ? `Server confirmed the original action (${result.authoritative_reference}).` : 'Server found no original action. The journal keeps it pending; only its original workflow may submit it again.');
      setEntryToReconcile(null);
    } catch (cause) {
      setError(describe(cause));
    } finally { setBusy(false); }
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
      ? `HQ requires ${clientVersion.latest_version}. This till is on ${clientVersion.client_version}. ${clientVersion.operations_impact || 'Update before continuing operations.'}`
      : clientVersion.update_available
        ? `HQ published ${clientVersion.latest_version}. ${clientVersion.operations_impact || 'Install when the shift allows.'}`
        : `Aligned with HQ release ${clientVersion.latest_version || clientVersion.client_version}. Rechecks daily.`;

  return <View style={styles.root} accessibilityLabel="Sync Centre">
    <View style={styles.header}><View style={styles.headerCopy}><Text style={styles.kicker}>Authoritative recovery</Text><Text style={styles.title}>Sync Centre</Text><Text style={styles.body}>Refreshes status only. It never blindly replays payment, collection, supply or clinical decisions.</Text></View><Pressable accessibilityRole="button" disabled={busy} onPress={() => void refresh()} style={[styles.secondary, busy && styles.disabled]}><Text style={styles.secondaryLabel}>{busy ? 'Refreshing…' : 'Refresh'}</Text></Pressable></View>
    {error ? <View accessibilityLiveRegion="assertive" style={styles.error}><Text style={styles.errorText}>{error}</Text></View> : null}
    {notice ? <View accessibilityLiveRegion="polite" style={styles.success}><Text style={styles.successText}>{notice}</Text></View> : null}
    <ScrollView contentContainerStyle={[styles.scroll, readableColumn]}>
      <View style={styles.statusGrid}>
        <StatusCard title="HQ client alignment" state={versionState} detail={versionDetail} />
        <StatusCard title="Clinical authority" state={clinicalConnected === true ? 'SAFE' : clinicalConnected === false ? 'BLOCKING' : 'ACTION_REQUIRED'} detail={clinicalConnected === true ? 'Clinical ruleset endpoint is reachable. Offline decisions are not replayed here.' : clinicalConnected === false ? 'Clinical authority is unavailable. Dispensing stays fail-closed.' : 'Checking clinical authority.'} />
        <StatusCard title="Operational context" state={runtime?.readiness === 'READY' ? 'SAFE' : runtime ? 'ACTION_REQUIRED' : 'BLOCKING'} detail={runtime ? runtime.notices[0] || `Register status: ${runtime.readiness.toLowerCase()}.` : 'Operational context is unavailable.'} />
        <StatusCard title="Printing" state={printCounts.retryRequired > 0 ? 'ACTION_REQUIRED' : 'SAFE'} detail={printCounts.retryRequired > 0 ? `${printCounts.retryRequired} print job${plural(printCounts.retryRequired)} requires a controlled retry.` : `${printCounts.queued} queued or rendered document${plural(printCounts.queued)} on this device.`} actionLabel="Open Print Centre" onAction={onOpenPrint} />
        <StatusCard title="Retail" state="ACTION_REQUIRED" detail="Retail is currently online-only. No offline retail queue is exposed or retried from Sync Centre." />
      </View>
      <View style={styles.journal}><View style={styles.journalHeader}><View style={styles.headerCopy}><Text style={styles.kicker}>Device journal</Text><Text style={styles.sectionTitle}>Dispensing and payment recovery</Text></View><View style={styles.count}><Text style={styles.countLabel}>{entries.length} retained</Text></View></View>
        {!journal ? <Text style={styles.body}>Secure local journal is unavailable; no local action is assumed complete.</Text> : null}
        {unknownEntries.length > 0 ? <Text style={styles.warning}>{unknownEntries.length} consequential action{plural(unknownEntries.length)} need server reconciliation before the affected episode can continue.</Text> : null}
        {entries.length === 0 ? <Text style={styles.body}>No local dispensing, payment or collection action is awaiting recovery.</Text> : entries.map((entry) => <JournalEntry key={entry.id} entry={entry} busy={busy} onReconcile={() => setEntryToReconcile(entry)} />)}
        {pendingEntries.length > 0 ? <Text style={styles.meta}>Pending items are retained for audit. Sync Centre does not dispatch them; return to their original workflow when ready.</Text> : null}
      </View>
    </ScrollView>
    {busy ? <ActivityIndicator color={action.primary} style={styles.progress} /> : null}
    {entryToReconcile ? <ReconciliationModal entry={entryToReconcile} busy={busy} onClose={() => !busy && setEntryToReconcile(null)} onConfirm={() => void reconcile()} /> : null}
  </View>;
}

function StatusCard({ title, state, detail, actionLabel, onAction }: { readonly title: string; readonly state: keyof typeof statusPalette; readonly detail: string; readonly actionLabel?: string; readonly onAction?: () => void }) {
  const palette = statusPalette[state];
  return <View style={[styles.statusCard, { borderTopColor: palette.accent }]}><Text style={styles.kicker}>{title}</Text><Text style={[styles.state, { color: palette.foreground }]}>{state === 'SAFE' ? 'Current' : state === 'BLOCKING' ? 'Attention required' : 'Review'}</Text><Text style={styles.meta}>{detail}</Text>{actionLabel && onAction ? <Pressable accessibilityRole="button" onPress={onAction} style={styles.secondary}><Text style={styles.secondaryLabel}>{actionLabel}</Text></Pressable> : null}</View>;
}

function JournalEntry({ entry, busy, onReconcile }: { readonly entry: OfflineAction; readonly busy: boolean; readonly onReconcile: () => void }) {
  const state = entry.state === 'CONFIRMED' ? 'SAFE' : entry.state === 'NEEDS_RECONCILIATION' ? 'BLOCKING' : 'ACTION_REQUIRED';
  const palette = statusPalette[state];
  return <View style={[styles.entry, { borderLeftColor: palette.accent }]}><View style={styles.entryHeader}><View style={styles.headerCopy}><Text style={styles.entryTitle}>{entry.type.replace(/_/g, ' ')}</Text><Text style={styles.meta}>Episode {entry.episodeId} · attempt {entry.attempts} · {formatDate(entry.queuedAt)}</Text></View><View style={[styles.statusChip, { backgroundColor: palette.surface, borderColor: palette.border }]}><Text style={[styles.statusChipText, { color: palette.foreground }]}>{entry.state.replace(/_/g, ' ')}</Text></View></View>{entry.failureReason ? <Text style={styles.warning}>{entry.failureReason}</Text> : null}{entry.state === 'NEEDS_RECONCILIATION' ? <Pressable accessibilityRole="button" disabled={busy} onPress={onReconcile} style={[styles.secondary, busy && styles.disabled]}><Text style={styles.secondaryLabel}>Query original action</Text></Pressable> : null}</View>;
}

function ReconciliationModal({ entry, busy, onClose, onConfirm }: { readonly entry: OfflineAction; readonly busy: boolean; readonly onClose: () => void; readonly onConfirm: () => void }) {
  return <Modal visible transparent animationType="fade" onRequestClose={onClose}><View style={styles.modalBackdrop} accessibilityViewIsModal><View style={styles.modalCard} accessibilityLabel="Authoritative reconciliation"><Text style={styles.kicker}>Authoritative reconciliation</Text><Text style={styles.title}>Query original {entry.type.toLowerCase()} action</Text><Text style={styles.body}>TibaTrace will query the server using this exact idempotency key. It will not resend, cancel or modify the original action.</Text><Text selectable style={styles.key}>{entry.idempotencyKey}</Text><View style={styles.modalActions}><Pressable accessibilityRole="button" disabled={busy} onPress={onClose} style={[styles.secondary, busy && styles.disabled]}><Text style={styles.secondaryLabel}>Back</Text></Pressable><Pressable accessibilityRole="button" disabled={busy} onPress={onConfirm} style={[styles.primary, busy && styles.disabled]}><Text style={styles.primaryLabel}>{busy ? 'Working…' : 'Query server'}</Text></Pressable></View></View></View></Modal>;
}

function plural(count: number): string { return count === 1 ? '' : 's'; }
function formatDate(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? 'Timestamp unavailable' : date.toLocaleString(); }
function describe(cause: unknown): string { return cause instanceof Error ? cause.message : String(cause); }

const styles = StyleSheet.create({
  root: { flex: 1, padding: spacing.lg, gap: spacing.md },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: spacing.md },
  headerCopy: { flex: 1, gap: 3 },
  kicker: { color: text.secondary, fontSize: fontSize.meta, textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: '700' },
  title: { color: text.primary, fontSize: fontSize.screenTitle, fontWeight: '700' },
  sectionTitle: { color: text.primary, fontSize: fontSize.sectionTitle, fontWeight: '700' },
  entryTitle: { color: text.primary, fontSize: fontSize.caption, fontWeight: '700' },
  body: { color: text.secondary, fontSize: fontSize.body, lineHeight: 20 },
  meta: { color: text.secondary, fontSize: fontSize.meta, lineHeight: 18 },
  error: { padding: spacing.md, borderRadius: 8, backgroundColor: statusPalette.BLOCKING.surface },
  errorText: { color: statusPalette.BLOCKING.foreground, fontSize: fontSize.body },
  success: { padding: spacing.md, borderRadius: 8, backgroundColor: statusPalette.SAFE.surface },
  successText: { color: statusPalette.SAFE.foreground, fontSize: fontSize.body },
  scroll: { gap: spacing.md, paddingBottom: spacing.xxxl },
  statusGrid: { gap: spacing.md },
  statusCard: { gap: spacing.sm, padding: spacing.md, borderWidth: 1, borderTopWidth: 4, borderColor: surface.border, borderRadius: 12, backgroundColor: surface.raised },
  state: { fontSize: fontSize.bodyLarge, fontWeight: '700' },
  journal: { gap: spacing.md, padding: spacing.md, borderWidth: 1, borderColor: surface.border, borderRadius: 12, backgroundColor: surface.raised },
  journalHeader: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.md, alignItems: 'flex-start' },
  count: { paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: 999, backgroundColor: surface.sunken },
  countLabel: { color: text.secondary, fontSize: fontSize.meta, fontWeight: '700' },
  warning: { color: statusPalette.BLOCKING.foreground, fontSize: fontSize.caption, lineHeight: 18 },
  entry: { gap: spacing.sm, padding: spacing.md, borderWidth: 1, borderLeftWidth: 4, borderColor: surface.border, borderRadius: 10, backgroundColor: surface.page },
  entryHeader: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.sm, alignItems: 'flex-start' },
  statusChip: { paddingHorizontal: spacing.sm, paddingVertical: 4, borderWidth: 1, borderRadius: 999 },
  statusChipText: { fontSize: fontSize.meta, fontWeight: '700' },
  secondary: { alignSelf: 'flex-start', minHeight: 40, justifyContent: 'center', paddingHorizontal: spacing.md, borderWidth: 1, borderColor: surface.borderStrong, borderRadius: 8, backgroundColor: surface.raised },
  secondaryLabel: { color: text.primary, fontSize: fontSize.caption, fontWeight: '700' },
  primary: { minHeight: 44, justifyContent: 'center', paddingHorizontal: spacing.md, borderRadius: 8, backgroundColor: action.primary },
  primaryLabel: { color: action.primaryForeground, fontSize: fontSize.caption, fontWeight: '700' },
  disabled: { opacity: 0.55, backgroundColor: surface.sunken },
  progress: { position: 'absolute', top: spacing.lg, right: spacing.lg },
  modalBackdrop: { flex: 1, justifyContent: 'center', padding: spacing.lg, backgroundColor: 'rgba(5, 18, 42, 0.56)' },
  modalCard: { gap: spacing.md, padding: spacing.xl, borderRadius: 14, backgroundColor: surface.raised },
  key: { padding: spacing.sm, borderRadius: 8, backgroundColor: surface.sunken, color: text.primary, fontSize: fontSize.caption, fontFamily: 'monospace' },
  modalActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm },
});
