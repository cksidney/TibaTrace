import { fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

type PrintStatus = 'QUEUED' | 'RENDERED' | 'SENDING' | 'PRINTED' | 'FAILED' | 'RETRY_REQUIRED' | 'CANCELLED';
type PrintActionKind = 'simulate' | 'retry' | 'reprint' | 'cancel';

interface PosPrintJob {
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

export function PrintCentreScreen({ apiFetch, deviceId }: { readonly apiFetch: typeof fetch; readonly deviceId: string }) {
  const [jobs, setJobs] = useState<readonly PosPrintJob[]>([]);
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
    void refresh();
  }, [refresh]);

  const openAction = (kind: PrintActionKind, job: PosPrintJob) => {
    setNotice('');
    setReason('');
    setSimulatedOutcome('success');
    setActiveAction({ kind, job });
  };

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
    <View style={styles.root} accessibilityLabel="Print Centre">
      <View style={styles.header}>
        <View style={styles.headerCopy}>
          <Text style={styles.kicker}>Durable document queue</Text>
          <Text style={styles.title}>Print Centre</Text>
          <Text style={styles.body}>This terminal shows its own branch/device queue. Simulator results validate queue controls only; physical printer certification is still required.</Text>
        </View>
        <Pressable accessibilityRole="button" disabled={busy} onPress={() => void refresh()} style={[styles.secondary, busy && styles.disabled]}>
          <Text style={styles.secondaryLabel}>{busy ? 'Refreshing…' : 'Refresh'}</Text>
        </Pressable>
      </View>

      <View style={styles.simulatorNotice} accessibilityLabel="Simulator-only mode">
        <Text style={styles.noticeTitle}>Simulator-only mode</Text>
        <Text style={styles.noticeBody}>No Bluetooth, network, ESC/POS, spooler, cash-drawer or scanner device is claimed as operational.</Text>
      </View>
      {error ? <View accessibilityLiveRegion="assertive" style={styles.error}><Text style={styles.errorText}>{error}</Text></View> : null}
      {notice ? <View accessibilityLiveRegion="polite" style={styles.success}><Text style={styles.successText}>{notice}</Text></View> : null}

      <ScrollView contentContainerStyle={styles.list}>
        {jobs.map((job) => <PrintJobCard key={job.id} job={job} busy={busy} onAction={openAction} />)}
        {jobs.length === 0 && !busy ? <View style={styles.empty}><Text style={styles.sectionTitle}>No print jobs for this device</Text><Text style={styles.body}>Completed payments create an immutable receipt snapshot and its first queued document job.</Text></View> : null}
      </ScrollView>

      {busy ? <ActivityIndicator color="#12854A" style={styles.progress} /> : null}
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
    </View>
  );
}

function PrintJobCard({ job, busy, onAction }: { readonly job: PosPrintJob; readonly busy: boolean; readonly onAction: (kind: PrintActionKind, job: PosPrintJob) => void }) {
  const palette = statusPalette[statusPaletteKey(job.status)];
  const canSimulate = job.status === 'QUEUED' || job.status === 'RENDERED';
  const canCancel = job.status === 'QUEUED' || job.status === 'RENDERED';
  return (
    <View style={[styles.job, { borderLeftColor: palette.accent }]}>
      <View style={styles.jobHeader}>
        <View style={styles.headerCopy}>
          <Text style={styles.kicker}>{job.document_type.replace(/_/g, ' ').toLowerCase()}</Text>
          <Text style={styles.sectionTitle}>{job.document_number}</Text>
          <Text style={styles.meta}>Copy {job.copy_number} · {job.copy_classification.toLowerCase()} · {formatDate(job.requested_at)}</Text>
        </View>
        <View style={[styles.status, { backgroundColor: palette.surface, borderColor: palette.border }]}><Text style={[styles.statusText, { color: palette.foreground }]}>{job.status.replace(/_/g, ' ')}</Text></View>
      </View>
      <View style={styles.metadata}><Meta label="Transport" value={job.transport === 'SIMULATOR' ? 'Simulator' : job.transport.replace(/_/g, ' ')} /><Meta label="Attempts" value={String(job.attempt_count)} /><Meta label="Printer" value={job.printer || 'Simulator target'} /><Meta label="Printed" value={job.printed_at ? formatDate(job.printed_at) : 'Not confirmed'} /></View>
      {job.failure_message ? <Text style={styles.failure}>{job.failure_code ? `${job.failure_code}: ` : ''}{job.failure_message}</Text> : null}
      {job.reprint_reason ? <Text style={styles.meta}>Reprint reason: {job.reprint_reason}</Text> : null}
      {job.cancellation_reason ? <Text style={styles.meta}>Cancellation reason: {job.cancellation_reason}</Text> : null}
      <View style={styles.actions}>
        {canSimulate ? <ActionButton label="Run simulator" disabled={busy} onPress={() => onAction('simulate', job)} /> : null}
        {job.status === 'RETRY_REQUIRED' ? <ActionButton label="Retry job" disabled={busy} onPress={() => onAction('retry', job)} /> : null}
        {job.status === 'PRINTED' ? <ActionButton label="Request reprint" disabled={busy} onPress={() => onAction('reprint', job)} /> : null}
        {canCancel ? <ActionButton label="Cancel job" disabled={busy} onPress={() => onAction('cancel', job)} /> : null}
      </View>
    </View>
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
  const title = action.kind === 'simulate' ? 'Run deterministic simulator' : action.kind === 'retry' ? 'Retry existing print job' : action.kind === 'reprint' ? 'Request reprint' : 'Cancel queued print job';
  const confirmLabel = action.kind === 'simulate' ? 'Run simulator' : action.kind === 'retry' ? 'Return to queue' : action.kind === 'reprint' ? 'Queue reprint' : 'Cancel job';
  const ready = !busy && (!requiresReason || reason.trim().length > 0);
  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.modalBackdrop} accessibilityViewIsModal>
        <View style={styles.modalCard} accessibilityLabel="Controlled document action">
          <Text style={styles.kicker}>Controlled document action</Text>
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.body}>Document {action.job.document_number}, copy {action.job.copy_number}. The immutable document snapshot will not change.</Text>
          {action.kind === 'simulate' ? <View style={styles.choiceGroup}>
            <Text style={styles.fieldLabel}>Simulator outcome</Text>
            <Choice label="Confirm document printed in simulator" selected={simulatedOutcome === 'success'} onPress={() => onOutcomeChange('success')} />
            <Choice label="Record retryable simulator failure" selected={simulatedOutcome === 'retryable-failure'} onPress={() => onOutcomeChange('retryable-failure')} />
            <Text style={styles.meta}>No physical printer receives this document.</Text>
          </View> : null}
          {action.kind === 'retry' ? <Text style={styles.meta}>Retry retains the same job and document identity; it does not create another receipt.</Text> : null}
          {requiresReason ? <View style={styles.field}><Text style={styles.fieldLabel}>{action.kind === 'reprint' ? 'Reprint reason (required)' : 'Cancellation reason (required)'}</Text><TextInput multiline value={reason} onChangeText={onReasonChange} style={styles.input} textAlignVertical="top" autoFocus /></View> : null}
          <View style={styles.modalActions}>
            <Pressable accessibilityRole="button" disabled={busy} onPress={onClose} style={[styles.secondary, busy && styles.disabled]}><Text style={styles.secondaryLabel}>Back</Text></Pressable>
            <Pressable accessibilityRole="button" accessibilityState={{ disabled: !ready }} disabled={!ready} onPress={onConfirm} style={[styles.primary, !ready && styles.disabled]}><Text style={[styles.primaryLabel, !ready && styles.primaryLabelDisabled]}>{busy ? 'Working…' : confirmLabel}</Text></Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function Meta({ label, value }: { readonly label: string; readonly value: string }) {
  return <View style={styles.metaItem}><Text style={styles.metaLabel}>{label}</Text><Text numberOfLines={1} style={styles.metaValue}>{value}</Text></View>;
}

function Choice({ label, selected, onPress }: { readonly label: string; readonly selected: boolean; readonly onPress: () => void }) {
  return <Pressable accessibilityRole="radio" accessibilityState={{ selected }} onPress={onPress} style={[styles.choice, selected && styles.choiceSelected]}><View style={[styles.radio, selected && styles.radioSelected]}>{selected ? <View style={styles.radioDot} /> : null}</View><Text style={styles.choiceLabel}>{label}</Text></Pressable>;
}

function ActionButton({ label, disabled, onPress }: { readonly label: string; readonly disabled: boolean; readonly onPress: () => void }) {
  return <Pressable accessibilityRole="button" disabled={disabled} onPress={onPress} style={[styles.actionButton, disabled && styles.disabled]}><Text style={styles.actionLabel}>{label}</Text></Pressable>;
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

const styles = StyleSheet.create({
  root: { flex: 1, padding: spacing.lg, gap: spacing.md },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: spacing.md },
  headerCopy: { flex: 1, gap: 3 },
  kicker: { color: text.secondary, fontSize: fontSize.meta, textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: '700' },
  title: { color: text.primary, fontSize: fontSize.screenTitle, fontWeight: '700' },
  sectionTitle: { color: text.primary, fontSize: fontSize.sectionTitle, fontWeight: '700' },
  body: { color: text.secondary, fontSize: fontSize.body, lineHeight: 20 },
  meta: { color: text.secondary, fontSize: fontSize.meta, lineHeight: 18 },
  simulatorNotice: { gap: 4, padding: spacing.md, borderWidth: 1, borderColor: statusPalette.ACTION_REQUIRED.border, borderRadius: 10, backgroundColor: statusPalette.ACTION_REQUIRED.surface },
  noticeTitle: { color: statusPalette.ACTION_REQUIRED.foreground, fontSize: fontSize.caption, fontWeight: '700' },
  noticeBody: { color: statusPalette.ACTION_REQUIRED.foreground, fontSize: fontSize.meta, lineHeight: 18 },
  error: { padding: spacing.md, borderRadius: 8, backgroundColor: statusPalette.BLOCKING.surface },
  errorText: { color: statusPalette.BLOCKING.foreground, fontSize: fontSize.body },
  success: { padding: spacing.md, borderRadius: 8, backgroundColor: statusPalette.SAFE.surface },
  successText: { color: statusPalette.SAFE.foreground, fontSize: fontSize.body },
  list: { gap: spacing.md, paddingBottom: spacing.xxxl },
  empty: { gap: spacing.sm, padding: spacing.xxl, borderWidth: 1, borderColor: surface.border, borderRadius: 12, backgroundColor: surface.raised },
  job: { gap: spacing.md, padding: spacing.md, borderWidth: 1, borderLeftWidth: 5, borderColor: surface.border, borderRadius: 12, backgroundColor: surface.raised },
  jobHeader: { flexDirection: 'row', gap: spacing.sm, justifyContent: 'space-between', alignItems: 'flex-start' },
  status: { paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: 999, borderWidth: 1 },
  statusText: { fontSize: fontSize.meta, fontWeight: '700' },
  metadata: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  metaItem: { flexGrow: 1, flexBasis: '42%', gap: 2 },
  metaLabel: { color: text.secondary, fontSize: fontSize.meta, textTransform: 'uppercase', letterSpacing: 0.4 },
  metaValue: { color: text.primary, fontSize: fontSize.caption },
  failure: { color: statusPalette.BLOCKING.foreground, fontSize: fontSize.caption, lineHeight: 18 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  actionButton: { minHeight: 40, justifyContent: 'center', paddingHorizontal: spacing.md, borderWidth: 1, borderColor: surface.borderStrong, borderRadius: 8, backgroundColor: surface.raised },
  actionLabel: { color: text.primary, fontSize: fontSize.caption, fontWeight: '700' },
  secondary: { minHeight: 40, justifyContent: 'center', paddingHorizontal: spacing.md, borderWidth: 1, borderColor: surface.borderStrong, borderRadius: 8, backgroundColor: surface.raised },
  secondaryLabel: { color: text.primary, fontSize: fontSize.caption, fontWeight: '700' },
  primary: { minHeight: 44, justifyContent: 'center', paddingHorizontal: spacing.md, borderRadius: 8, backgroundColor: '#12854A' },
  primaryLabel: { color: '#fff', fontSize: fontSize.caption, fontWeight: '700' },
  primaryLabelDisabled: { color: text.tertiary },
  disabled: { opacity: 0.55, backgroundColor: surface.sunken },
  progress: { position: 'absolute', top: spacing.lg, right: spacing.lg },
  modalBackdrop: { flex: 1, justifyContent: 'center', padding: spacing.lg, backgroundColor: 'rgba(5, 18, 42, 0.56)' },
  modalCard: { gap: spacing.md, padding: spacing.xl, borderRadius: 14, backgroundColor: surface.raised },
  choiceGroup: { gap: spacing.sm, padding: spacing.md, borderWidth: 1, borderColor: surface.border, borderRadius: 8 },
  choice: { minHeight: 42, flexDirection: 'row', gap: spacing.sm, alignItems: 'center', padding: spacing.sm, borderWidth: 1, borderColor: surface.border, borderRadius: 8 },
  choiceSelected: { borderColor: '#075E37', backgroundColor: '#F0FBF5' },
  radio: { width: 18, height: 18, borderWidth: 2, borderColor: text.secondary, borderRadius: 9, alignItems: 'center', justifyContent: 'center' },
  radioSelected: { borderColor: '#12854A' },
  radioDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#12854A' },
  choiceLabel: { flex: 1, color: text.primary, fontSize: fontSize.caption, fontWeight: '600' },
  field: { gap: spacing.xs },
  fieldLabel: { color: text.primary, fontSize: fontSize.caption, fontWeight: '700' },
  input: { minHeight: 92, padding: spacing.sm, borderWidth: 1, borderColor: surface.borderStrong, borderRadius: 8, backgroundColor: surface.raised, color: text.primary, fontSize: fontSize.body },
  modalActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm },
});
