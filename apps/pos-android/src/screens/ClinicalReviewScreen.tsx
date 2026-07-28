import type { ScreeningDecision, ScreeningOverride, ScreeningResult } from '@dawatrace/shared/clinical/index.js';
import { controlSize, fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import type { DispensingEpisodeDTO } from '@dawatrace/shared/dispensing/index.js';
import { useMemo, useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

type ReviewDecision =
  | 'APPROVE'
  | 'APPROVE_WITH_CONDITIONS'
  | 'RETURN_FOR_CORRECTION'
  | 'REJECT'
  | 'CONTACT_PRESCRIBER'
  | 'REQUIRE_ALTERNATIVE'
  | 'REQUEST_MORE_INFORMATION';

type OverrideAction = 'request' | 'start-review' | 'approve' | 'reject' | 'revoke';

interface OverrideActionInput {
  readonly action: OverrideAction;
  readonly overrideId?: string;
  readonly findingId: string;
  readonly overrideReason?: string;
  readonly requestedReason?: string;
  readonly supportingNotes?: string;
  readonly clinicalJustification?: string;
  readonly conditions?: string;
  readonly expiresAt?: string;
  readonly reason?: string;
}

const DECISIONS: readonly { value: ReviewDecision; label: string; consequence: string }[] = [
  { value: 'APPROVE', label: 'Approve', consequence: 'Releases only this screened clinical context.' },
  { value: 'APPROVE_WITH_CONDITIONS', label: 'Approve with conditions', consequence: 'Keeps supply blocked until conditions are fulfilled and the basket is screened again.' },
  { value: 'RETURN_FOR_CORRECTION', label: 'Return for correction', consequence: 'Keeps supply blocked until the changed basket is screened again.' },
  { value: 'REJECT', label: 'Reject', consequence: 'Keeps supply blocked for this finding.' },
  { value: 'CONTACT_PRESCRIBER', label: 'Contact prescriber', consequence: 'Keeps supply blocked pending clarification.' },
  { value: 'REQUIRE_ALTERNATIVE', label: 'Require alternative', consequence: 'Keeps supply blocked until an alternative is screened.' },
  { value: 'REQUEST_MORE_INFORMATION', label: 'Request more information', consequence: 'Keeps supply blocked until the missing information is recorded.' },
];

const OVERRIDE_REASONS = [
  { value: 'CLINICALLY_JUSTIFIED', label: 'Clinically justified' },
  { value: 'PRESCRIBER_CONFIRMED', label: 'Prescriber confirmed' },
  { value: 'KNOWN_AND_MONITORED', label: 'Known and monitored' },
  { value: 'OTHER', label: 'Other' },
] as const;

export function ClinicalReviewScreen({
  episode,
  result,
  busy,
  onBack,
  onRequestReview,
  onSubmit,
  onOverrideAction,
}: {
  readonly episode: DispensingEpisodeDTO;
  readonly result: ScreeningResult;
  readonly busy: boolean;
  readonly onBack: () => void;
  readonly onRequestReview: () => Promise<void>;
  readonly onSubmit: (input: {
    findingId: string;
    decision: ReviewDecision;
    clinicalJustification: string;
    conditions: string;
    followUpActions: string;
  }) => Promise<void>;
  readonly onOverrideAction: (input: OverrideActionInput) => Promise<void>;
}) {
  const finding = result.findings.find((item) => item.blocking) ?? result.findings[0];
  const [decision, setDecision] = useState<ReviewDecision>('APPROVE');
  const [justification, setJustification] = useState('');
  const [conditions, setConditions] = useState('');
  const [followUpActions, setFollowUpActions] = useState('');
  const [error, setError] = useState('');
  const history = useMemo(
    () => result.decisions.filter((item) => item.findingId === finding?.id),
    [finding?.id, result.decisions],
  );

  if (!finding) {
    return <View style={styles.empty}><Text style={styles.title}>Clinical review unavailable</Text><Text style={styles.body}>No clinical finding is available for review.</Text></View>;
  }

  const selected = DECISIONS.find((item) => item.value === decision)!;
  const requiresConditions = decision === 'APPROVE_WITH_CONDITIONS';
  const ready = !busy && justification.trim().length > 0 && (!requiresConditions || conditions.trim().length > 0);

  const requestReview = () => {
    setError('');
    void onRequestReview().catch((cause: unknown) => setError(describe(cause)));
  };

  const submit = () => {
    setError('');
    void onSubmit({
      findingId: finding.id,
      decision,
      clinicalJustification: justification.trim(),
      conditions: conditions.trim(),
      followUpActions: followUpActions.trim(),
    }).catch((cause: unknown) => setError(describe(cause)));
  };

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <View style={styles.headerText}><Text style={styles.kicker}>Clinical decision workspace</Text><Text style={styles.title}>Pharmacist review</Text></View>
        <Pressable accessibilityRole="button" onPress={onBack} style={styles.secondary}><Text style={styles.secondaryLabel}>Back</Text></Pressable>
      </View>
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.patientCard}>
          <Meta label="Patient" value={episode.patient_name ?? 'Name not recorded'} />
          <Meta label="Prescription" value={episode.prescription_number ?? episode.dispensing_number} />
          <Meta label="Context" value={`${result.contextHash.slice(0, 14)}…`} />
          <Meta label="Ruleset" value={result.ruleSetVersion || 'Not recorded'} />
        </View>

        <View style={styles.findingCard}>
          <Text style={styles.kicker}>{finding.category.replace(/_/g, ' ').toLowerCase()}</Text>
          <Text style={styles.findingTitle}>{finding.title}</Text>
          <Text style={styles.body}>{finding.explanation}</Text>
          {finding.recommendation ? <Text style={styles.recommendation}>{finding.recommendation}</Text> : null}
          <Text style={styles.findingStatus}>Status: {(finding.resolutionStatus || 'OPEN').replace(/_/g, ' ')}</Text>
        </View>

        <View style={styles.formCard}>
          <View style={styles.formHeader}>
            <View><Text style={styles.kicker}>Decision</Text><Text style={styles.sectionTitle}>Record pharmacist decision</Text></View>
            <Pressable accessibilityRole="button" disabled={busy} onPress={requestReview} style={[styles.secondary, busy && styles.disabled]}><Text style={styles.secondaryLabel}>Request review</Text></Pressable>
          </View>
          {DECISIONS.map((option) => (
            <Pressable key={option.value} accessibilityRole="radio" accessibilityState={{ selected: decision === option.value }} onPress={() => setDecision(option.value)} style={[styles.choice, decision === option.value && styles.choiceSelected]}>
              <View style={[styles.radio, decision === option.value && styles.radioSelected]}>{decision === option.value ? <View style={styles.radioDot} /> : null}</View>
              <View style={styles.choiceText}><Text style={styles.choiceLabel}>{option.label}</Text><Text style={styles.choiceDetail}>{option.consequence}</Text></View>
            </Pressable>
          ))}
          <Text style={styles.consequence}>{selected.consequence}</Text>
          <Field label="Clinical rationale (required)" value={justification} onChange={setJustification} />
          {requiresConditions ? <Field label="Conditions of approval (required)" value={conditions} onChange={setConditions} /> : null}
          <Field label="Follow-up actions" value={followUpActions} onChange={setFollowUpActions} />
          {error ? <View accessibilityLiveRegion="assertive" style={styles.error}><Text style={styles.errorText}>{error}</Text></View> : null}
          <Pressable accessibilityRole="button" accessibilityState={{ disabled: !ready }} disabled={!ready} onPress={submit} style={[styles.primary, !ready && styles.disabled]}>
            <Text style={[styles.primaryLabel, !ready && styles.primaryLabelDisabled]}>{busy ? 'Recording decision…' : 'Record clinical decision'}</Text>
          </Pressable>
        </View>

        <DecisionHistory decisions={history} />
        <OverrideLifecycle
          finding={finding}
          overrides={result.overrides.filter((item) => item.findingId === finding.id)}
          busy={busy}
          onSubmit={onOverrideAction}
          onError={setError}
        />
      </ScrollView>
    </View>
  );
}

function Field({ label, value, onChange }: { readonly label: string; readonly value: string; readonly onChange: (value: string) => void }) {
  return <View style={styles.field}><Text style={styles.fieldLabel}>{label}</Text><TextInput multiline value={value} onChangeText={onChange} style={styles.input} textAlignVertical="top" /></View>;
}

function DecisionHistory({ decisions }: { readonly decisions: readonly ScreeningDecision[] }) {
  return <View style={styles.history}><Text style={styles.kicker}>Audit history</Text><Text style={styles.sectionTitle}>Prior clinical decisions</Text>
    {decisions.length === 0 ? <Text style={styles.body}>No prior decision has been recorded for this finding.</Text> : decisions.map((item) => <View key={item.id} style={styles.historyItem}><Text style={styles.choiceLabel}>{item.decision.replace(/_/g, ' ')}</Text><Text style={styles.historyMeta}>{item.pharmacistName || 'Pharmacist'} · {item.createdAt || 'Recorded now'}</Text><Text style={styles.body}>{item.clinicalJustification}</Text>{item.conditions ? <Text style={styles.body}>Conditions: {item.conditions}</Text> : null}{item.followUpActions ? <Text style={styles.body}>Follow-up: {item.followUpActions}</Text> : null}</View>)}</View>;
}

function OverrideLifecycle({
  finding,
  overrides,
  busy,
  onSubmit,
  onError,
}: {
  readonly finding: { readonly id: string; readonly overrideAllowed: boolean };
  readonly overrides: readonly ScreeningOverride[];
  readonly busy: boolean;
  readonly onSubmit: (input: OverrideActionInput) => Promise<void>;
  readonly onError: (message: string) => void;
}) {
  const [action, setAction] = useState<OverrideAction | null>(null);
  const [overrideReason, setOverrideReason] = useState('CLINICALLY_JUSTIFIED');
  const [requestedReason, setRequestedReason] = useState('');
  const [supportingNotes, setSupportingNotes] = useState('');
  const [clinicalJustification, setClinicalJustification] = useState('');
  const [conditions, setConditions] = useState('');
  const [expiresAt, setExpiresAt] = useState('');
  const [reason, setReason] = useState('');
  const current = overrides[0];
  const mayRequest = finding.overrideAllowed && (!current || ['REJECTED', 'REVOKED', 'EXPIRED'].includes(current.status));
  const modalReady = !busy && (
    action === 'start-review'
    || (action === 'request' && requestedReason.trim().length > 0)
    || (action === 'approve' && clinicalJustification.trim().length > 0)
    || ((action === 'reject' || action === 'revoke') && reason.trim().length > 0)
  );
  const actionLabel = action === 'request'
    ? 'Request override'
    : action === 'start-review'
      ? 'Start pharmacist review'
      : action === 'approve'
        ? 'Approve override'
        : action === 'reject'
          ? 'Reject override'
          : 'Revoke override';

  const submit = () => {
    if (!action || !modalReady) return;
    onError('');
    void onSubmit({
      action,
      ...(current ? { overrideId: current.id } : {}),
      findingId: finding.id,
      overrideReason,
      requestedReason: requestedReason.trim(),
      supportingNotes: supportingNotes.trim(),
      clinicalJustification: clinicalJustification.trim(),
      conditions: conditions.trim(),
      ...(expiresAt.trim() ? { expiresAt: expiresAt.trim() } : {}),
      reason: reason.trim(),
    }).then(() => setAction(null)).catch((cause: unknown) => onError(describe(cause)));
  };

  return <View style={styles.history} accessibilityLabel="Governed clinical override lifecycle">
    <Text style={styles.kicker}>Controlled exception</Text>
    <Text style={styles.sectionTitle}>Clinical override lifecycle</Text>
    <Text style={styles.body}>Overrides are time-bound, scoped to this screening, and require a separate authorised approval. They cannot bypass an unresolved finding.</Text>
    {current ? <View style={styles.historyItem}>
      <Text style={styles.choiceLabel}>{current.status.replace(/_/g, ' ')}</Text>
      <Text style={styles.historyMeta}>{current.overrideReason.replace(/_/g, ' ')} · {current.createdAt || 'Recorded now'}</Text>
      <Text style={styles.body}>Request: {current.requestedReason || 'Not recorded'}</Text>
      {current.clinicalJustification ? <Text style={styles.body}>Approval rationale: {current.clinicalJustification}</Text> : null}
      {current.conditions ? <Text style={styles.body}>Conditions: {current.conditions}</Text> : null}
      {current.expiresAt ? <Text style={styles.body}>Expires: {new Date(current.expiresAt).toLocaleString()}</Text> : null}
      {current.rejectionReason ? <Text style={styles.body}>Rejection: {current.rejectionReason}</Text> : null}
      {current.revocationReason ? <Text style={styles.body}>Revocation: {current.revocationReason}</Text> : null}
      {current.consumedEvent ? <Text style={styles.body}>Consumed by: {current.consumedEvent}</Text> : null}
    </View> : <Text style={styles.body}>No override has been requested for this finding.</Text>}
    <View style={styles.overrideActions}>
      {mayRequest ? <ActionButton label="Request override" busy={busy} onPress={() => setAction('request')} /> : null}
      {current?.status === 'REQUESTED' ? <ActionButton label="Start review" busy={busy} onPress={() => setAction('start-review')} /> : null}
      {['REQUESTED', 'UNDER_REVIEW'].includes(current?.status ?? '') ? <ActionButton label="Approve override" primary busy={busy} onPress={() => setAction('approve')} /> : null}
      {['REQUESTED', 'UNDER_REVIEW'].includes(current?.status ?? '') ? <ActionButton label="Reject override" busy={busy} onPress={() => setAction('reject')} /> : null}
      {['APPROVED', 'APPROVED_WITH_CONDITIONS'].includes(current?.status ?? '') ? <ActionButton label="Revoke override" busy={busy} onPress={() => setAction('revoke')} /> : null}
    </View>
    <Modal visible={action !== null} transparent animationType="fade" onRequestClose={() => setAction(null)}>
      <View style={styles.modalBackdrop} accessibilityViewIsModal>
        <View style={styles.modalCard}>
          <Text style={styles.kicker}>Controlled clinical action</Text>
          <Text style={styles.sectionTitle}>{actionLabel}</Text>
          {action === 'request' ? <>
            <Text style={styles.fieldLabel}>Override reason</Text>
            <View style={styles.reasonChoices}>
              {OVERRIDE_REASONS.map((option) => <Pressable key={option.value} accessibilityRole="radio" accessibilityState={{ selected: overrideReason === option.value }} onPress={() => setOverrideReason(option.value)} style={[styles.reasonChoice, overrideReason === option.value && styles.choiceSelected]}><Text style={styles.secondaryLabel}>{option.label}</Text></Pressable>)}
            </View>
            <Field label="Request rationale (required)" value={requestedReason} onChange={setRequestedReason} />
            <Field label="Supporting notes" value={supportingNotes} onChange={setSupportingNotes} />
          </> : null}
          {action === 'approve' ? <>
            <Field label="Clinical approval rationale (required)" value={clinicalJustification} onChange={setClinicalJustification} />
            <Field label="Conditions (optional; keeps supply blocked until rescreened)" value={conditions} onChange={setConditions} />
            <View style={styles.field}><Text style={styles.fieldLabel}>Expiry ISO time (optional; policy window applies by default)</Text><TextInput value={expiresAt} onChangeText={setExpiresAt} placeholder="2026-07-28T12:30:00Z" placeholderTextColor={text.tertiary} style={styles.singleLineInput} /></View>
          </> : null}
          {action === 'reject' || action === 'revoke' ? <Field label={`${action === 'reject' ? 'Rejection' : 'Revocation'} reason (required)`} value={reason} onChange={setReason} /> : null}
          {action === 'start-review' ? <Text style={styles.body}>This records that an authorised pharmacist has opened the request for review. It does not approve supply.</Text> : null}
          <View style={styles.modalActions}>
            <Pressable accessibilityRole="button" onPress={() => setAction(null)} style={styles.secondary}><Text style={styles.secondaryLabel}>Cancel</Text></Pressable>
            <Pressable accessibilityRole="button" accessibilityState={{ disabled: !modalReady }} disabled={!modalReady} onPress={submit} style={[styles.primary, !modalReady && styles.disabled]}><Text style={[styles.primaryLabel, !modalReady && styles.primaryLabelDisabled]}>{actionLabel}</Text></Pressable>
          </View>
        </View>
      </View>
    </Modal>
  </View>;
}

function ActionButton({ label, primary = false, busy, onPress }: { readonly label: string; readonly primary?: boolean; readonly busy: boolean; readonly onPress: () => void }) {
  return <Pressable accessibilityRole="button" disabled={busy} onPress={onPress} style={[primary ? styles.actionPrimary : styles.actionSecondary, busy && styles.disabled]}><Text style={primary ? styles.actionPrimaryLabel : styles.secondaryLabel}>{label}</Text></Pressable>;
}

function Meta({ label, value }: { readonly label: string; readonly value: string }) {
  return <View style={styles.meta}><Text style={styles.metaLabel}>{label}</Text><Text style={styles.metaValue}>{value}</Text></View>;
}

function describe(cause: unknown): string { return cause instanceof Error ? cause.message : String(cause); }

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: surface.page },
  header: { minHeight: 68, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: 1, borderBottomColor: surface.border, backgroundColor: surface.raised },
  headerText: { flexShrink: 1 },
  scroll: { padding: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xxxl },
  title: { marginTop: 3, fontSize: fontSize.screenTitle, color: text.primary, fontWeight: '700' },
  sectionTitle: { marginTop: 3, fontSize: fontSize.sectionTitle, color: text.primary, fontWeight: '700' },
  kicker: { fontSize: fontSize.caption, color: text.tertiary, textTransform: 'uppercase', letterSpacing: 0.7 },
  patientCard: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.lg, padding: spacing.lg, borderRadius: 12, borderWidth: 1, borderColor: surface.border, backgroundColor: surface.raised },
  meta: { minWidth: 130, flexGrow: 1 },
  metaLabel: { fontSize: fontSize.meta, color: text.tertiary, textTransform: 'uppercase' },
  metaValue: { marginTop: 4, color: text.primary, fontSize: fontSize.body },
  findingCard: { padding: spacing.lg, borderRadius: 12, borderWidth: 1, borderLeftWidth: 5, borderColor: statusPalette.BLOCKING.border, borderLeftColor: statusPalette.BLOCKING.accent, backgroundColor: surface.raised },
  findingTitle: { marginTop: 4, fontSize: fontSize.sectionTitle, color: text.primary, fontWeight: '700' },
  body: { marginTop: spacing.sm, fontSize: fontSize.body, color: text.secondary, lineHeight: fontSize.body * 1.45 },
  recommendation: { marginTop: spacing.sm, fontSize: fontSize.body, color: text.primary, fontWeight: '600', lineHeight: fontSize.body * 1.45 },
  findingStatus: { marginTop: spacing.md, fontSize: fontSize.caption, color: text.tertiary, fontWeight: '700', textTransform: 'uppercase' },
  formCard: { padding: spacing.lg, borderRadius: 12, borderWidth: 1, borderColor: surface.border, backgroundColor: surface.raised, gap: spacing.md },
  formHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.md },
  choice: { flexDirection: 'row', gap: spacing.md, padding: spacing.md, borderWidth: 1, borderColor: surface.border, borderRadius: 10 },
  choiceSelected: { borderColor: '#075E37', backgroundColor: '#E6F5EA' },
  radio: { width: 20, height: 20, borderRadius: 10, borderWidth: 2, borderColor: surface.borderStrong, alignItems: 'center', justifyContent: 'center', marginTop: 1 },
  radioSelected: { borderColor: '#075E37' },
  radioDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: '#075E37' },
  choiceText: { flex: 1 },
  choiceLabel: { fontSize: fontSize.body, color: text.primary, fontWeight: '700' },
  choiceDetail: { marginTop: 2, fontSize: fontSize.caption, color: text.secondary, lineHeight: fontSize.caption * 1.35 },
  consequence: { fontSize: fontSize.caption, color: text.secondary, lineHeight: fontSize.caption * 1.35 },
  field: { gap: spacing.xs },
  fieldLabel: { fontSize: fontSize.caption, color: text.secondary, fontWeight: '700' },
  input: { minHeight: 96, padding: spacing.md, borderRadius: 8, borderWidth: 1, borderColor: surface.borderStrong, backgroundColor: surface.raised, color: text.primary, fontSize: fontSize.body },
  singleLineInput: { minHeight: controlSize.touchTarget, paddingHorizontal: spacing.md, borderRadius: 8, borderWidth: 1, borderColor: surface.borderStrong, backgroundColor: surface.raised, color: text.primary, fontSize: fontSize.body },
  primary: { minHeight: controlSize.touchTargetLarge, borderRadius: 10, alignItems: 'center', justifyContent: 'center', backgroundColor: '#075E37' },
  primaryLabel: { color: text.inverse, fontSize: fontSize.bodyLarge, fontWeight: '700' },
  primaryLabelDisabled: { color: text.tertiary },
  secondary: { minHeight: controlSize.touchTarget, justifyContent: 'center', paddingHorizontal: spacing.md, borderWidth: 1, borderColor: surface.borderStrong, borderRadius: 8 },
  secondaryLabel: { color: text.primary, fontSize: fontSize.caption, fontWeight: '700' },
  disabled: { backgroundColor: surface.sunken, opacity: 0.7 },
  error: { padding: spacing.md, borderRadius: 8, backgroundColor: statusPalette.BLOCKING.surface, borderLeftWidth: 4, borderLeftColor: statusPalette.BLOCKING.accent },
  errorText: { color: statusPalette.BLOCKING.foreground, fontSize: fontSize.body },
  history: { padding: spacing.lg, borderRadius: 12, borderWidth: 1, borderColor: surface.border, backgroundColor: surface.raised },
  historyItem: { marginTop: spacing.md, paddingTop: spacing.md, borderTopWidth: 1, borderTopColor: surface.border },
  historyMeta: { marginTop: 3, color: text.tertiary, fontSize: fontSize.caption },
  overrideActions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.md },
  actionPrimary: { minHeight: controlSize.touchTarget, justifyContent: 'center', paddingHorizontal: spacing.md, borderRadius: 8, backgroundColor: '#075E37' },
  actionPrimaryLabel: { color: text.inverse, fontSize: fontSize.caption, fontWeight: '700' },
  actionSecondary: { minHeight: controlSize.touchTarget, justifyContent: 'center', paddingHorizontal: spacing.md, borderWidth: 1, borderColor: surface.borderStrong, borderRadius: 8 },
  modalBackdrop: { flex: 1, justifyContent: 'center', padding: spacing.lg, backgroundColor: 'rgba(10, 24, 43, 0.52)' },
  modalCard: { gap: spacing.md, padding: spacing.lg, borderRadius: 12, backgroundColor: surface.raised, maxHeight: '90%' },
  modalActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm },
  reasonChoices: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  reasonChoice: { minHeight: controlSize.touchTarget, justifyContent: 'center', paddingHorizontal: spacing.md, borderWidth: 1, borderColor: surface.border, borderRadius: 8 },
  empty: { flex: 1, padding: spacing.xl, justifyContent: 'center', alignItems: 'center' },
});
