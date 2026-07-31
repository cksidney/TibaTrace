import {
  PosOperationsClient,
  type CashMovementDTO,
  type PosOperationalRuntimeDTO,
  type ShiftReportDTO,
} from '@dawatrace/shared/operational/index.js';
import { action, fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import { formatDecimal } from '@dawatrace/shared/money.js';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { columnTrack, readableColumn } from '../components/tibatrace/layout';

const DENOMINATIONS = ['1000', '500', '200', '100', '50', '20', '10', '5', '1'] as const;
const MOVEMENT_KINDS = [
  'CASH_IN',
  'CASH_OUT',
  'FLOAT_TOP_UP',
  'SAFE_DROP',
  'PETTY_CASH',
  'BANKING',
  'CORRECTION',
  'OTHER_AUTHORISED_MOVEMENT',
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

export function RegisterCentreScreen({
  apiBaseUrl,
  apiFetch,
  deviceId,
}: {
  readonly apiBaseUrl: string;
  readonly apiFetch: typeof fetch;
  readonly deviceId: string;
}) {
  const client = useMemo(
    () => new PosOperationsClient(`${apiBaseUrl}/api/pos/shift`, { fetcher: apiFetch }),
    [apiBaseUrl, apiFetch],
  );
  const [runtime, setRuntime] = useState<PosOperationalRuntimeDTO | null>(null);
  const [movements, setMovements] = useState<readonly CashMovementDTO[]>([]);
  const [reports, setReports] = useState<readonly ShiftReportDTO[]>([]);
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
    void refresh();
  }, [refresh]);

  const allowed = new Set(runtime?.allowed_actions ?? []);
  const pendingHandover = runtime?.register_session?.operator_shifts.find(
    (shift) => shift.state === 'HANDOVER_REQUESTED',
  );
  const latestX = reports.find((report) => report.report_type === 'X');
  const latestZ = reports.find((report) => report.report_type === 'Z');

  const complete = async (message: string) => {
    setActiveAction(null);
    setNotice(message);
    await refresh();
  };

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <View style={styles.headerCopy}>
          <Text style={styles.kicker}>Accountable till operations</Text>
          <Text style={styles.title}>Register Centre</Text>
          <Text style={styles.body}>Blind cash counts, controlled movements, immutable reports and shift handover.</Text>
        </View>
        <Pressable accessibilityRole="button" disabled={busy} onPress={() => void refresh()} style={styles.secondary}>
          <Text style={styles.secondaryLabel}>{busy ? '…' : 'Refresh'}</Text>
        </Pressable>
      </View>

      {error ? <View accessibilityLiveRegion="assertive" style={styles.error}><Text style={styles.errorText}>{error}</Text></View> : null}
      {notice ? <View accessibilityLiveRegion="polite" style={styles.success}><Text style={styles.successText}>{notice}</Text></View> : null}
      {busy ? <ActivityIndicator color={action.primary} /> : null}

      <ScrollView contentContainerStyle={[styles.scroll, readableColumn]}>
        <View style={styles.summaryGrid}>
          <Summary label="Register" value={runtime?.register?.code ?? 'Unassigned'} />
          <Summary label="State" value={runtime?.register?.state ?? 'Unavailable'} />
          <Summary label="Business date" value={runtime?.business_day?.business_date ?? 'Unavailable'} />
          <Summary label="Operator" value={runtime?.operator_shift?.operator_username ?? 'No active shift'} />
        </View>

        {runtime?.notices.length ? (
          <View style={styles.attention}>
            <Text style={styles.attentionTitle}>Operational attention</Text>
            {runtime.notices.map((item) => <Text key={item} style={styles.attentionText}>{item}</Text>)}
          </View>
        ) : null}

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Register lifecycle</Text>
          <Text style={styles.body}>Every action opens a confirmation step before it reaches the server.</Text>
          <View style={styles.actionGrid}>
            <Action label="Open register" detail="Opening float count" disabled={!allowed.has('OPEN_REGISTER') || busy} onPress={() => setActiveAction({ kind: 'open' })} />
            <Action label="Cash movement" detail="Cash in, safe drop or banking" disabled={!allowed.has('RECORD_CASH_MOVEMENT') || busy} onPress={() => setActiveAction({ kind: 'movement' })} />
            <Action label="X report" detail="Interim snapshot only" disabled={!allowed.has('GENERATE_X_REPORT') || busy} onPress={() => setActiveAction({ kind: 'x-report' })} />
            <Action label="Close register" detail="Blind count and final Z" disabled={!allowed.has('CLOSE_REGISTER') || busy || closureHasExternalBlocker(runtime)} onPress={() => setActiveAction({ kind: 'close' })} />
            <Action
              label={allowed.has('CANCEL_HANDOVER') ? 'Cancel handover' : 'Request handover'}
              detail="Transfer accountability"
              disabled={(!allowed.has('REQUEST_HANDOVER') && !allowed.has('CANCEL_HANDOVER')) || busy}
              onPress={() => setActiveAction({ kind: allowed.has('CANCEL_HANDOVER') ? 'cancel-handover' : 'request-handover' })}
            />
            <Action
              label="Accept handover"
              detail={pendingHandover ? `From ${pendingHandover.operator_username}` : 'None pending'}
              disabled={!allowed.has('ACCEPT_HANDOVER') || !pendingHandover || busy}
              onPress={() => pendingHandover && setActiveAction({ kind: 'accept-handover', shiftId: pendingHandover.id })}
            />
          </View>
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Cash movement approvals</Text>
          <Text style={styles.body}>A movement creator cannot approve their own record.</Text>
          {movements.length === 0 ? <Text style={styles.empty}>No cash movements in this session.</Text> : movements.slice().reverse().map((movement) => (
            <View key={movement.id} style={styles.listItem}>
              <View style={styles.listCopy}>
                <Text style={styles.listTitle}>{movement.kind.replace(/_/g, ' ')} · {movement.currency} {movement.amount}</Text>
                <Text style={styles.meta}>{movement.reason_code} · {movement.created_by_username}</Text>
              </View>
              {movement.approved_at ? (
                <Text style={styles.approved}>Approved</Text>
              ) : (
                <Pressable
                  accessibilityRole="button"
                  disabled={!allowed.has('APPROVE_CASH_MOVEMENT') || busy}
                  onPress={() => setActiveAction({ kind: 'approve', movement })}
                  style={styles.secondary}
                >
                  <Text style={styles.secondaryLabel}>Review</Text>
                </Pressable>
              )}
            </View>
          ))}
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Immutable reports</Text>
          {!latestX && !latestZ ? <Text style={styles.empty}>No X or Z report exists for this register.</Text> : null}
          {latestX ? <ReportRow report={latestX} onPress={() => setActiveAction({ kind: 'view-report', report: latestX })} /> : null}
          {latestZ ? <ReportRow report={latestZ} onPress={() => setActiveAction({ kind: 'view-report', report: latestZ })} /> : null}
        </View>
      </ScrollView>

      <Modal transparent visible={activeAction !== null} animationType="fade" onRequestClose={() => !busy && setActiveAction(null)}>
        {activeAction ? (
          <ActionModal
            action={activeAction}
            busy={busy}
            client={client}
            deviceId={deviceId}
            runtime={runtime}
            onBusy={setBusy}
            onClose={() => !busy && setActiveAction(null)}
            onError={setError}
            onComplete={complete}
          />
        ) : null}
      </Modal>
    </View>
  );
}

function ActionModal({
  action,
  busy,
  client,
  deviceId,
  runtime,
  onBusy,
  onClose,
  onError,
  onComplete,
}: {
  readonly action: RegisterAction;
  readonly busy: boolean;
  readonly client: PosOperationsClient;
  readonly deviceId: string;
  readonly runtime: PosOperationalRuntimeDTO | null;
  readonly onBusy: (busy: boolean) => void;
  readonly onClose: () => void;
  readonly onError: (message: string) => void;
  readonly onComplete: (message: string) => Promise<void>;
}) {
  const [counts, setCounts] = useState<Record<string, string>>({});
  const [movementKind, setMovementKind] = useState<string>('SAFE_DROP');
  const [amount, setAmount] = useState('');
  const [reasonCode, setReasonCode] = useState('');
  const [description, setDescription] = useState('');
  const [reference, setReference] = useState('');
  const [reason, setReason] = useState('');
  const report = action.kind === 'view-report' ? action.report : null;
  const total = denominationTotal(counts);

  const submit = async () => {
    if (!runtime?.register || report || busy) return;
    onBusy(true);
    onError('');
    try {
      if (action.kind === 'open') {
        await client.openRegister(runtime.register.id, { deviceId, openingAmount: total, denominations: denominationPayload(counts) });
        await onComplete(`Register opened with ${runtime.register.currency} ${total}.`);
      } else if (action.kind === 'movement') {
        await client.recordCashMovement({ deviceId, kind: movementKind, amount, reasonCode, description, reference });
        await onComplete('Cash movement recorded for separate approval.');
      } else if (action.kind === 'approve') {
        await client.approveCashMovement(action.movement.id);
        await onComplete('Cash movement approved by this operator.');
      } else if (action.kind === 'x-report') {
        const generated = await client.generateXReport(runtime.register.id, deviceId);
        await onComplete(`X report ${generated.report_number} generated.`);
      } else if (action.kind === 'close') {
        const generated = await client.closeRegister(runtime.register.id, { deviceId, declaredAmount: total, denominations: denominationPayload(counts), reason });
        await onComplete(`Z report ${generated.report_number} finalised; the register is closed.`);
      } else if (action.kind === 'request-handover' && runtime.operator_shift) {
        await client.requestHandover(runtime.operator_shift.id, deviceId, reason);
        await onComplete('Handover requested. Lock the device for the incoming operator.');
      } else if (action.kind === 'cancel-handover' && runtime.operator_shift) {
        await client.cancelHandover(runtime.operator_shift.id, deviceId);
        await onComplete('Handover cancelled; accountability remains unchanged.');
      } else if (action.kind === 'accept-handover') {
        await client.acceptHandover(action.shiftId, deviceId);
        await onComplete('Handover accepted; this operator is now accountable.');
      }
    } catch (cause) {
      onError(describe(cause));
    } finally {
      onBusy(false);
    }
  };

  const ready = !busy && (action.kind !== 'movement' || (Number(amount) > 0 && reasonCode.trim().length > 0));

  return (
    <View style={styles.modalBackdrop}>
      <View accessibilityViewIsModal style={styles.modalCard}>
        <Text style={styles.kicker}>Governed register action</Text>
        <Text style={styles.title}>{actionTitle(action)}</Text>
        <ScrollView contentContainerStyle={styles.modalScroll}>
          {report ? <ReportSnapshot report={report} /> : null}
          {action.kind === 'open' || action.kind === 'close' ? (
            <>
              <Text style={styles.body}>Count physical cash by denomination. Expected closing cash stays hidden until confirmation.</Text>
              <View style={styles.denominationGrid}>
                {DENOMINATIONS.map((face) => (
                  <View key={face} style={styles.denomination}>
                    <Text style={styles.fieldLabel}>{runtime?.register?.currency ?? 'KES'} {face}</Text>
                    <TextInput
                      accessibilityLabel={`${face} denomination count`}
                      keyboardType="number-pad"
                      value={counts[face] ?? ''}
                      onChangeText={(value) => setCounts({ ...counts, [face]: value.replace(/[^\d]/g, '') })}
                      style={styles.input}
                    />
                  </View>
                ))}
              </View>
              <View style={styles.total}><Text style={styles.totalLabel}>Counted total</Text><Text style={styles.totalValue}>{runtime?.register?.currency ?? 'KES'} {total}</Text></View>
              {action.kind === 'close' ? <Field label="Closing note (optional)" value={reason} onChange={setReason} multiline /> : null}
            </>
          ) : null}
          {action.kind === 'movement' ? (
            <>
              <Text style={styles.fieldLabel}>Movement type</Text>
              <View style={styles.choiceGrid}>
                {MOVEMENT_KINDS.map((kind) => (
                  <Pressable key={kind} onPress={() => setMovementKind(kind)} style={[styles.choice, movementKind === kind && styles.choiceSelected]}>
                    <Text style={styles.choiceLabel}>{kind.replace(/_/g, ' ')}</Text>
                  </Pressable>
                ))}
              </View>
              <Field label="Amount" value={amount} onChange={setAmount} keyboardType="decimal-pad" />
              <Field label="Reason code" value={reasonCode} onChange={setReasonCode} />
              <Field label="Reference" value={reference} onChange={setReference} />
              <Field label="Description" value={description} onChange={setDescription} multiline />
            </>
          ) : null}
          {action.kind === 'approve' ? <Confirmation title={`${action.movement.kind.replace(/_/g, ' ')} · ${action.movement.currency} ${action.movement.amount}`} detail={`Recorded by ${action.movement.created_by_username} for ${action.movement.reason_code}.`} /> : null}
          {action.kind === 'x-report' ? <Confirmation title="Generate interim X report" detail="This snapshot never closes the session or resets register totals." /> : null}
          {action.kind === 'request-handover' ? <Field label="Handover note (optional)" value={reason} onChange={setReason} multiline /> : null}
          {action.kind === 'cancel-handover' ? <Confirmation title="Cancel pending handover" detail="The current operator remains accountable." /> : null}
          {action.kind === 'accept-handover' ? <Confirmation title="Accept till accountability" detail="The outgoing shift closes and a new accountable shift starts for this operator." /> : null}
        </ScrollView>
        <View style={styles.modalActions}>
          <Pressable accessibilityRole="button" disabled={busy} onPress={onClose} style={styles.secondary}><Text style={styles.secondaryLabel}>{report ? 'Close' : 'Back'}</Text></Pressable>
          {!report ? <Pressable accessibilityRole="button" disabled={!ready} onPress={() => void submit()} style={[styles.primary, !ready && styles.disabled]}><Text style={styles.primaryLabel}>{busy ? 'Working…' : confirmLabel(action)}</Text></Pressable> : null}
        </View>
      </View>
    </View>
  );
}

function Field({ label, value, onChange, multiline = false, keyboardType = 'default' }: { readonly label: string; readonly value: string; readonly onChange: (value: string) => void; readonly multiline?: boolean; readonly keyboardType?: 'default' | 'decimal-pad' }) {
  return <View style={styles.field}><Text style={styles.fieldLabel}>{label}</Text><TextInput keyboardType={keyboardType} multiline={multiline} value={value} onChangeText={onChange} style={[styles.input, multiline && styles.multiline]} /></View>;
}

function Summary({ label, value }: { readonly label: string; readonly value: string }) {
  return <View style={styles.summary}><Text style={styles.kicker}>{label}</Text><Text style={styles.summaryValue}>{value}</Text></View>;
}

function Action({ label, detail, disabled, onPress }: { readonly label: string; readonly detail: string; readonly disabled: boolean; readonly onPress: () => void }) {
  return <Pressable accessibilityRole="button" disabled={disabled} onPress={onPress} style={[styles.action, disabled && styles.disabled]}><Text style={styles.actionTitle}>{label}</Text><Text style={styles.meta}>{detail}</Text></Pressable>;
}

function ReportRow({ report, onPress }: { readonly report: ShiftReportDTO; readonly onPress: () => void }) {
  return <View style={styles.listItem}><View style={styles.listCopy}><Text style={styles.listTitle}>{report.report_type} · {report.report_number}</Text><Text style={styles.meta}>{formatDate(report.generated_at)}</Text></View><Pressable accessibilityRole="button" onPress={onPress} style={styles.secondary}><Text style={styles.secondaryLabel}>View</Text></Pressable></View>;
}

function ReportSnapshot({ report }: { readonly report: ShiftReportDTO }) {
  const variance = report.snapshot.variance;
  return (
    <View style={styles.report}>
      <Confirmation title={`${report.report_type} report ${report.report_number}`} detail={`Generated by ${report.generated_by_username} on ${formatDate(report.generated_at)}.`} />
      <ReportValue label="Opening cash" value={`${report.snapshot.currency} ${report.snapshot.cash.opening}`} />
      <ReportValue label="Cash sales" value={`${report.snapshot.currency} ${report.snapshot.cash.cash_sales}`} />
      <ReportValue label="Expected closing" value={`${report.snapshot.currency} ${report.snapshot.cash.expected_closing}`} />
      <ReportValue label="Grand total" value={`${report.snapshot.currency} ${report.snapshot.tenders.grand_total}`} />
      {variance ? <ReportValue label="Declared cash" value={`${report.snapshot.currency} ${variance.declared}`} /> : null}
      {variance ? <ReportValue label="Variance" value={`${report.snapshot.currency} ${variance.difference} · ${variance.classification}`} /> : null}
    </View>
  );
}

function ReportValue({ label, value }: { readonly label: string; readonly value: string }) {
  return <View style={styles.reportValue}><Text style={styles.kicker}>{label}</Text><Text style={styles.listTitle}>{value}</Text></View>;
}

function Confirmation({ title, detail }: { readonly title: string; readonly detail: string }) {
  return <View style={styles.confirmation}><Text style={styles.listTitle}>{title}</Text><Text style={styles.body}>{detail}</Text></View>;
}

function denominationPayload(counts: Readonly<Record<string, string>>): Record<string, number> {
  return Object.fromEntries(Object.entries(counts).filter(([, count]) => Number(count) > 0).map(([face, count]) => [face, Number(count)]));
}

function denominationTotal(counts: Readonly<Record<string, string>>): string {
  const cents = Object.entries(counts).reduce((sum, [face, count]) => sum + Math.round(Number(face) * 100) * (Number.parseInt(count || '0', 10) || 0), 0);
  return formatDecimal(cents / 100, 2);
}

function closureHasExternalBlocker(runtime: PosOperationalRuntimeDTO | null): boolean {
  return Boolean(runtime?.closure_eligibility.blocking_reasons.some((reason) => !reason.toLowerCase().includes('closing cash declaration')));
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

function confirmLabel(action: RegisterAction): string {
  if (action.kind === 'open') return 'Count and open';
  if (action.kind === 'movement') return 'Record movement';
  if (action.kind === 'approve') return 'Approve';
  if (action.kind === 'x-report') return 'Generate X';
  if (action.kind === 'close') return 'Count and close';
  if (action.kind === 'request-handover') return 'Request';
  if (action.kind === 'cancel-handover') return 'Cancel handover';
  if (action.kind === 'accept-handover') return 'Accept';
  return 'Confirm';
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
  scroll: { gap: spacing.md, paddingBottom: spacing.xxxl },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: spacing.md },
  headerCopy: { flex: 1, gap: 3 },
  kicker: { color: text.secondary, fontSize: fontSize.meta, textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: '700' },
  title: { color: text.primary, fontSize: fontSize.screenTitle, fontWeight: '700' },
  sectionTitle: { color: text.primary, fontSize: fontSize.sectionTitle, fontWeight: '700' },
  body: { color: text.secondary, fontSize: fontSize.body, lineHeight: 20 },
  meta: { color: text.secondary, fontSize: fontSize.meta, lineHeight: 18 },
  error: { padding: spacing.md, borderRadius: 8, backgroundColor: statusPalette.BLOCKING.surface },
  errorText: { color: statusPalette.BLOCKING.foreground, fontSize: fontSize.body },
  success: { padding: spacing.md, borderRadius: 8, backgroundColor: statusPalette.SAFE.surface },
  successText: { color: statusPalette.SAFE.foreground, fontSize: fontSize.body },
  summaryGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  summary: { ...columnTrack(170), gap: 3, padding: spacing.md, borderWidth: 1, borderColor: surface.border, borderRadius: 10, backgroundColor: surface.raised },
  summaryValue: { color: text.primary, fontSize: fontSize.bodyLarge, fontWeight: '700' },
  attention: { gap: 4, padding: spacing.md, borderWidth: 1, borderColor: statusPalette.ACTION_REQUIRED.border, borderRadius: 10, backgroundColor: statusPalette.ACTION_REQUIRED.surface },
  attentionTitle: { color: statusPalette.ACTION_REQUIRED.foreground, fontSize: fontSize.caption, fontWeight: '700' },
  attentionText: { color: statusPalette.ACTION_REQUIRED.foreground, fontSize: fontSize.meta, lineHeight: 18 },
  card: { gap: spacing.md, padding: spacing.md, borderWidth: 1, borderColor: surface.border, borderRadius: 12, backgroundColor: surface.raised },
  actionGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  action: { ...columnTrack(190), minHeight: 76, gap: 4, justifyContent: 'center', padding: spacing.md, borderWidth: 1, borderColor: action.selectedBorder, borderRadius: 10, backgroundColor: action.selectedSurface },
  actionTitle: { color: text.primary, fontSize: fontSize.caption, fontWeight: '700' },
  listItem: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.sm, borderWidth: 1, borderColor: surface.border, borderRadius: 9, backgroundColor: surface.page },
  listCopy: { flex: 1, gap: 2 },
  listTitle: { color: text.primary, fontSize: fontSize.caption, fontWeight: '700' },
  approved: { color: statusPalette.SAFE.foreground, fontSize: fontSize.caption, fontWeight: '700' },
  empty: { color: text.secondary, fontSize: fontSize.body, textAlign: 'center', padding: spacing.lg },
  secondary: { minHeight: 40, justifyContent: 'center', paddingHorizontal: spacing.md, borderWidth: 1, borderColor: surface.borderStrong, borderRadius: 8, backgroundColor: surface.raised },
  secondaryLabel: { color: text.primary, fontSize: fontSize.caption, fontWeight: '700' },
  primary: { minHeight: 44, justifyContent: 'center', paddingHorizontal: spacing.md, borderRadius: 8, backgroundColor: action.primary },
  primaryLabel: { color: action.primaryForeground, fontSize: fontSize.caption, fontWeight: '700' },
  disabled: { opacity: 0.5, backgroundColor: surface.sunken },
  modalBackdrop: { flex: 1, justifyContent: 'center', padding: spacing.lg, backgroundColor: 'rgba(5, 18, 42, 0.56)' },
  modalCard: { maxHeight: '92%', gap: spacing.md, padding: spacing.xl, borderRadius: 14, backgroundColor: surface.raised },
  modalScroll: { gap: spacing.md },
  modalActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm },
  denominationGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  denomination: { ...columnTrack(96), gap: 3 },
  total: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: spacing.md, borderRadius: 8, backgroundColor: surface.inverse },
  totalLabel: { color: text.inverse, fontSize: fontSize.caption },
  totalValue: { color: text.inverse, fontSize: fontSize.bodyLarge, fontWeight: '700' },
  field: { gap: spacing.xs },
  fieldLabel: { color: text.primary, fontSize: fontSize.caption, fontWeight: '700' },
  input: { minHeight: 42, padding: spacing.sm, borderWidth: 1, borderColor: surface.borderStrong, borderRadius: 8, backgroundColor: surface.raised, color: text.primary, fontSize: fontSize.body },
  multiline: { minHeight: 84, textAlignVertical: 'top' },
  choiceGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  choice: { paddingHorizontal: spacing.sm, paddingVertical: spacing.sm, borderWidth: 1, borderColor: surface.border, borderRadius: 8 },
  choiceSelected: { borderColor: action.selectedBorder, backgroundColor: action.selectedSurface },
  choiceLabel: { color: text.primary, fontSize: fontSize.meta, fontWeight: '600' },
  confirmation: { gap: spacing.xs, padding: spacing.md, borderWidth: 1, borderColor: surface.border, borderRadius: 8, backgroundColor: surface.page },
  report: { gap: spacing.sm },
  reportValue: { gap: 2, padding: spacing.sm, borderBottomWidth: 1, borderBottomColor: surface.divider },
});
