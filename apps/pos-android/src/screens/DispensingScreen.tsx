import {
  STAGE_STATUS,
  action,
  controlSize,
  deriveStages,
  fontSize,
  nextAction,
  spacing,
  stageMarker,
  statusPalette,
  surface,
  text,
} from '@dawatrace/shared/design-system/index.js';
import type { StageView } from '@dawatrace/shared/design-system/index.js';
import type { BatchVerificationResponse, DispensingLineDTO } from '@dawatrace/shared/dispensing/index.js';
import type { DispensingEpisodeDTO } from '@dawatrace/shared/dispensing/index.js';
import type { TimelineEntry } from '@dawatrace/shared/dispensing/index.js';
import { TIMELINE_EVENTS, orderTimeline } from '@dawatrace/shared/dispensing/index.js';
import { formatInstant } from '@dawatrace/shared/clinical/index.js';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { readableColumn } from '../components/tibatrace/layout';
import { ClinicalSummaryCard, PatientBanner } from '../components/tibatrace/ClinicalSummaryCard';
import type { AndroidClinicalSummary } from '../components/tibatrace/ClinicalSummaryCard';
import { TibaTraceBrand } from '../components/tibatrace/TibaTraceBrand';

/**
 * Android dispensing episode.
 *
 * Touch-first, but driven by exactly the same shared derivation as Windows:
 * `deriveStages` and the gate come from the server's episode state, so the two
 * clients cannot disagree about whether supply is permitted.
 *
 * Now includes:
 * - Medicine lines list with status, batch and expiry
 * - Inline batch verification for AUTHORIZED lines
 * - Final-check comparison for PREPARED lines
 * - On-demand episode timeline
 */
export function DispensingScreen({
  episode,
  clinical,
  gateBlockedReason,
  canConfirmCollection,
  onConfirmCollection,
  onReviewFinding,
  apiFetch,
  onTransition,
}: {
  readonly episode: DispensingEpisodeDTO | null;
  readonly clinical: AndroidClinicalSummary;
  readonly gateBlockedReason: string;
  readonly canConfirmCollection: boolean;
  readonly onConfirmCollection?: (() => void) | undefined;
  readonly onReviewFinding?: (() => void) | undefined;
  readonly apiFetch?: typeof fetch | undefined;
  readonly onTransition?: (() => void) | undefined;
}) {
  const stages = deriveStages(episode, {
    screened: clinical.screened,
    safeToProceed: clinical.safeToProceed,
    stale: clinical.stale,
    pharmacistReviewRequired: clinical.blockingCount > 0,
  });
  const next = nextAction(stages);

  if (!episode) {
    return (
      <View style={styles.empty}>
        <TibaTraceBrand />
        <Text style={styles.emptyTitle}>No prescription loaded</Text>
        <Text style={styles.emptyBody}>Scan or search for a prescription to begin dispensing.</Text>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <View style={styles.brand}><TibaTraceBrand /></View>
      {/* The resolved name, not `patient`, which is the row's UUID. This banner
          is what an operator reads to confirm who they are dispensing for.

          An empty allergy list means the record is silent, which is not the
          clinical claim "no known allergies", so it stays UNKNOWN rather than
          becoming a reassuring NONE_KNOWN. */}
      <PatientBanner
        fullName={episode.patient_name ?? 'Name not recorded'}
        reference={episode.patient_number ?? episode.dispensing_number}
        allergyStatus={episode.allergies.length > 0 ? 'KNOWN_ALLERGY' : 'UNKNOWN'}
      />

      <ScrollView contentContainerStyle={[styles.scroll, readableColumn]}>
        {/* The clinical summary sits directly below the banner: on a handheld
            the blocker must be readable without scrolling. */}
        <ClinicalSummaryCard
          summary={clinical}
          {...(onReviewFinding ? { onReview: onReviewFinding } : {})}
        />

        <Text style={styles.sectionTitle}>Workflow</Text>
        <View style={styles.stepper}>
          {stages.map((stage) => (
            <StageRow key={stage.id} stage={stage} />
          ))}
        </View>

        {/* Medicine lines */}
        {episode.lines.length > 0 ? (
          <View>
            <Text style={styles.sectionTitle}>Prescription lines</Text>
            <View style={styles.lines}>
              {episode.lines.map((line) => (
                <LineCard
                  key={line.id}
                  line={line}
                  episodeId={episode.id}
                  apiFetch={apiFetch}
                  onTransition={onTransition}
                />
              ))}
            </View>
          </View>
        ) : null}

        {/* Episode timeline */}
        {apiFetch ? (
          <EpisodeTimelineSection
            episodeId={episode.id}
            apiFetch={apiFetch}
          />
        ) : null}
      </ScrollView>

      <View style={styles.actionBar}>
        <Text style={styles.nextLabel} numberOfLines={2}>
          {gateBlockedReason || `Next: ${next?.label ?? 'No action available'}`}
        </Text>
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ disabled: !canConfirmCollection }}
          disabled={!canConfirmCollection}
          onPress={onConfirmCollection}
          style={[styles.primary, !canConfirmCollection && styles.primaryDisabled]}
        >
          <Text style={[styles.primaryLabel, !canConfirmCollection && styles.primaryLabelDisabled]}>
            Confirm collection
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

/** A single prescription line card with status badge, batch/expiry, and
 *  contextual action widgets for AUTHORIZED and PREPARED states. */
function LineCard({
  line,
  episodeId,
  apiFetch,
  onTransition,
}: {
  readonly line: DispensingLineDTO;
  readonly episodeId: string;
  readonly apiFetch?: typeof fetch | undefined;
  readonly onTransition?: (() => void) | undefined;
}) {
  const [verifyResult, setVerifyResult] = useState<BatchVerificationResponse | null>(null);
  const [batchNumber, setBatchNumber] = useState('');
  const [verifying, setBusy] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [actionError, setActionError] = useState('');

  const statusMeta = lineStatusMeta(line.status);
  const palette = statusPalette[statusMeta.status];

  const isExpired = line.expiry_date_snapshot
    ? new Date(line.expiry_date_snapshot).getTime() < Date.now()
    : false;

  const verify = async () => {
    if (!apiFetch || !batchNumber.trim()) return;
    setBusy(true);
    setActionError('');
    try {
      const response = await apiFetch('/api/pos/dispensing/episodes/verify-batch/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          sku_id: line.supplied_sku || line.prescribed_sku,
          batch_number: batchNumber.trim(),
        }),
      });
      if (!response.ok) { setActionError(`Verify failed (${response.status}).`); return; }
      setVerifyResult(await response.json() as BatchVerificationResponse);
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const completeCheck = async () => {
    if (!apiFetch) return;
    setCompleting(true);
    setActionError('');
    try {
      const resp = await apiFetch(`/api/pos/dispensing/episodes/${episodeId}/transition-state/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ new_status: 'CHECKING' }),
      });
      if (!resp.ok) { setActionError(`Transition failed (${resp.status}).`); return; }
      onTransition?.();
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setCompleting(false);
    }
  };

  return (
    <View style={[styles.lineCard, { borderLeftColor: palette.accent }]}>
      {/* Header: medicine name + status */}
      <View style={styles.lineHeader}>
        <View style={styles.lineHeaderText}>
          <Text style={styles.medicineName}>{line.supplied_sku || line.prescribed_sku}</Text>
          {line.dosage_label_instructions ? (
            <Text style={styles.dosageInstructions}>{line.dosage_label_instructions}</Text>
          ) : null}
        </View>
        <View style={[styles.statusBadge, { backgroundColor: palette.surface }]}>
          <Text style={[styles.statusBadgeLabel, { color: palette.foreground }]}>
            {statusMeta.label}
          </Text>
        </View>
      </View>

      {/* Quantities and batch */}
      <View style={styles.lineFields}>
        <LineField label="Authorised" value={line.quantity_authorized} />
        <LineField label="Prepared" value={line.quantity_prepared} />
        <LineField label="Supplied" value={line.quantity_supplied} />
        <LineField label="Batch" value={line.batch_number_snapshot || '—'} />
        <LineField
          label="Expiry"
          value={line.expiry_date_snapshot ?? '—'}
          danger={isExpired}
        />
      </View>

      {isExpired ? (
        <View style={[styles.noticeBand, { backgroundColor: statusPalette.BLOCKING.surface }]}>
          <Text style={[styles.noticeText, { color: statusPalette.BLOCKING.foreground }]}>
            This batch has expired and cannot be supplied.
          </Text>
        </View>
      ) : null}

      {actionError ? (
        <View style={[styles.noticeBand, { backgroundColor: statusPalette.BLOCKING.surface }]}>
          <Text style={[styles.noticeText, { color: statusPalette.BLOCKING.foreground }]}>{actionError}</Text>
        </View>
      ) : null}

      {/* Batch verification — AUTHORIZED lines only */}
      {line.status === 'AUTHORIZED' && apiFetch ? (
        <View style={styles.actionSection}>
          <Text style={styles.actionSectionTitle}>Batch verification</Text>
          <View style={styles.batchRow}>
            <TextInput
              style={styles.batchInput}
              placeholder="Scan or type batch number"
              value={batchNumber}
              onChangeText={setBatchNumber}
              autoCapitalize="characters"
              returnKeyType="done"
              onSubmitEditing={() => void verify()}
            />
            <Pressable
              accessibilityRole="button"
              disabled={verifying || !batchNumber.trim()}
              onPress={() => void verify()}
              style={[styles.batchButton, (verifying || !batchNumber.trim()) && styles.buttonDisabled]}
            >
              <Text style={styles.batchButtonLabel}>{verifying ? 'Verifying…' : 'Verify'}</Text>
            </Pressable>
          </View>
          {verifyResult ? (
            <View style={[
              styles.verifyResult,
              { borderLeftColor: verifyResult.valid ? statusPalette.SAFE.accent : statusPalette.BLOCKING.accent },
            ]}>
              <Text style={[
                styles.verifyResultLabel,
                { color: verifyResult.valid ? statusPalette.SAFE.foreground : statusPalette.BLOCKING.foreground },
              ]}>
                {verifyResult.valid ? '✓ Verified' : '✗ Cannot be supplied'}
              </Text>
              <Text style={styles.verifyReason}>{verifyResult.reason}</Text>
              <View style={styles.lineFields}>
                <LineField label="Batch found" value={verifyResult.batch_found ? 'Yes' : 'No'} />
                <LineField label="Product match" value={verifyResult.sku_match ? 'Yes' : 'No'} />
                <LineField label="Release" value={verifyResult.release_status} />
                <LineField label="Available" value={verifyResult.quantity_available} />
              </View>
            </View>
          ) : null}
        </View>
      ) : null}

      {/* Final check — PREPARED lines */}
      {(line.status === 'PREPARED' || line.status === 'CHECKING') && apiFetch ? (
        <View style={styles.actionSection}>
          <Text style={styles.actionSectionTitle}>Final check</Text>
          {/* Prescribed vs prepared comparison */}
          <View style={styles.checkTable}>
            <CheckRow
              field="Product"
              prescribed={line.prescribed_sku}
              prepared={line.supplied_sku}
              matches={line.prescribed_sku === line.supplied_sku}
            />
            <CheckRow
              field="Quantity"
              prescribed={line.quantity_authorized}
              prepared={line.quantity_prepared}
              matches={
                Number.isFinite(Number(line.quantity_authorized)) &&
                Number.isFinite(Number(line.quantity_prepared)) &&
                Number(line.quantity_authorized) === Number(line.quantity_prepared)
              }
            />
            <CheckRow
              field="Batch"
              prescribed="—"
              prepared={line.batch_number_snapshot || '—'}
              matches={true}
            />
            <CheckRow
              field="Expiry"
              prescribed="—"
              prepared={line.expiry_date_snapshot ?? '—'}
              matches={true}
            />
          </View>
          {line.status === 'PREPARED' ? (
            <Pressable
              accessibilityRole="button"
              disabled={completing || isExpired}
              onPress={() => void completeCheck()}
              style={[styles.primary, (completing || isExpired) && styles.primaryDisabled, { marginTop: spacing.md }]}
            >
              <Text style={[styles.primaryLabel, (completing || isExpired) && styles.primaryLabelDisabled]}>
                {completing ? 'Recording…' : 'Complete final check'}
              </Text>
            </Pressable>
          ) : (
            <Text style={styles.checkCompletedNote}>Final check recorded.</Text>
          )}
        </View>
      ) : null}
    </View>
  );
}

function CheckRow({
  field,
  prescribed,
  prepared,
  matches,
}: {
  readonly field: string;
  readonly prescribed: string;
  readonly prepared: string;
  readonly matches: boolean;
}) {
  return (
    <View style={[styles.checkRowWrap, !matches && { backgroundColor: statusPalette.BLOCKING.surface }]}>
      <Text style={styles.checkField}>{field}</Text>
      <Text style={styles.checkValue}>{prescribed}</Text>
      <Text style={[styles.checkValue, !matches && { color: statusPalette.BLOCKING.foreground, fontWeight: '700' }]}>
        {prepared}{!matches ? ' ✗' : ''}
      </Text>
    </View>
  );
}

function LineField({
  label,
  value,
  danger,
}: {
  readonly label: string;
  readonly value: string;
  readonly danger?: boolean;
}) {
  return (
    <View style={styles.lineField}>
      <Text style={styles.lineFieldLabel}>{label}</Text>
      <Text style={[styles.lineFieldValue, danger && { color: statusPalette.BLOCKING.foreground, fontWeight: '700' }]}>
        {value}
      </Text>
    </View>
  );
}

/** Lazily fetches and renders the episode timeline. Errors are shown inline
 *  rather than hiding the section entirely. */
function EpisodeTimelineSection({
  episodeId,
  apiFetch,
}: {
  readonly episodeId: string;
  readonly apiFetch: typeof fetch;
}) {
  const [entries, setEntries] = useState<readonly TimelineEntry[] | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const response = await apiFetch(
        `/api/pos/dispensing/episodes/${episodeId}/timeline/`,
        { headers: { Accept: 'application/json' } },
      );
      if (!response.ok) { setError(`Timeline unavailable (${response.status}).`); return; }
      const data = await response.json() as TimelineEntry[] | { results?: TimelineEntry[] };
      setEntries(Array.isArray(data) ? data : (data.results ?? []));
    } catch {
      setError('Timeline could not be loaded.');
    }
  }, [apiFetch, episodeId]);

  useEffect(() => { void load(); }, [load]);

  return (
    <View>
      <Text style={styles.sectionTitle}>Episode history</Text>
      {error ? (
        <Text style={styles.timelineEmpty}>{error}</Text>
      ) : entries === null ? (
        <ActivityIndicator color={action.primary} style={{ margin: spacing.lg }} />
      ) : entries.length === 0 ? (
        <Text style={styles.timelineEmpty}>No history recorded yet.</Text>
      ) : (
        <View style={styles.timeline}>
          {orderTimeline(entries).map((entry) => {
            const presentation = TIMELINE_EVENTS[entry.type];
            const palette = statusPalette[presentation?.status ?? 'INFORMATION'];
            const notable = presentation?.notable ?? false;
            return (
              <View key={entry.id} style={styles.timelineRow}>
                <Text style={styles.timelineTime}>{formatInstant(entry.occurredAt)}</Text>
                <View
                  style={[
                    styles.timelineDot,
                    {
                      borderColor: palette.accent,
                      backgroundColor: notable ? palette.accent : 'transparent',
                    },
                  ]}
                />
                <View style={styles.timelineContent}>
                  <Text
                    style={[
                      styles.timelineLabel,
                      notable && { color: palette.foreground, fontWeight: '700' },
                    ]}
                  >
                    {presentation?.label ?? entry.type.replace(/_/g, ' ').toLowerCase()}
                  </Text>
                  <Text style={styles.timelineSummary}>
                    {entry.summary}{entry.actor ? ` · ${entry.actor}` : ''}
                  </Text>
                  {entry.reason ? (
                    <Text style={[styles.timelineReason, { color: palette.foreground }]}>
                      {entry.reason}
                    </Text>
                  ) : null}
                </View>
              </View>
            );
          })}
        </View>
      )}
    </View>
  );
}

function lineStatusMeta(status: string): { status: 'COMPLETED' | 'ACTION_REQUIRED' | 'SAFE' | 'INFORMATION' | 'BLOCKING' | 'DISABLED'; label: string } {
  switch (status) {
    case 'SUPPLIED': return { status: 'COMPLETED', label: 'Supplied' };
    case 'PARTIALLY_SUPPLIED': return { status: 'ACTION_REQUIRED', label: 'Partially supplied' };
    case 'CHECKED': return { status: 'SAFE', label: 'Final checked' };
    case 'PREPARED': return { status: 'INFORMATION', label: 'Prepared' };
    case 'AUTHORIZED': return { status: 'DISABLED', label: 'Not prepared' };
    case 'REVERSED': return { status: 'BLOCKING', label: 'Reversed' };
    default: return { status: 'ACTION_REQUIRED', label: status.replace(/_/g, ' ') };
  }
}

function StageRow({ stage }: { readonly stage: StageView }) {
  const palette = statusPalette[STAGE_STATUS[stage.state]];
  return (
    <View
      accessibilityLabel={`Step ${stage.step}, ${stage.label}, ${stage.state
        .replace(/_/g, ' ')
        .toLowerCase()}${stage.blockedReason ? `. ${stage.blockedReason}` : ''}`}
      style={[styles.stageRow, { borderLeftColor: palette.accent }]}
    >
      <Text style={[styles.stageStep, { color: palette.foreground }]}>
        {stageMarker(stage.state, stage.step)}
      </Text>
      <View style={styles.stageText}>
        <Text style={styles.stageLabel}>{stage.label}</Text>
        {stage.blockedReason ? (
          <Text style={[styles.stageReason, { color: palette.foreground }]}>
            {stage.blockedReason}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: surface.page },
  brand: { paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.xs },
  scroll: { paddingBottom: spacing.xxxl },
  sectionTitle: {
    marginHorizontal: spacing.lg,
    marginTop: spacing.xl,
    marginBottom: spacing.sm,
    fontSize: fontSize.caption,
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    color: text.tertiary,
  },
  stepper: { margin: spacing.lg, gap: spacing.sm },
  stageRow: {
    flexDirection: 'row',
    gap: spacing.md,
    alignItems: 'flex-start',
    backgroundColor: surface.raised,
    borderRadius: 10,
    borderLeftWidth: 4,
    padding: spacing.md,
  },
  stageStep: {
    fontSize: fontSize.caption,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
    minWidth: 16,
  },
  stageText: { flexShrink: 1 },
  stageLabel: { fontSize: fontSize.body, fontWeight: '600', color: text.primary },
  stageReason: { marginTop: 2, fontSize: fontSize.caption, lineHeight: fontSize.caption * 1.4 },
  // Lines
  lines: { marginHorizontal: spacing.lg, gap: spacing.md },
  lineCard: {
    backgroundColor: surface.raised,
    borderRadius: 12,
    borderLeftWidth: 4,
    borderLeftColor: surface.border,
    overflow: 'hidden',
  },
  lineHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    padding: spacing.md,
    gap: spacing.sm,
  },
  lineHeaderText: { flex: 1, gap: spacing.xs },
  medicineName: { fontSize: fontSize.bodyLarge, fontWeight: '700', color: text.primary },
  dosageInstructions: { fontSize: fontSize.body, color: text.secondary, lineHeight: fontSize.body * 1.4 },
  statusBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: 999,
    alignSelf: 'flex-start',
  },
  statusBadgeLabel: { fontSize: fontSize.meta, fontWeight: '700' },
  lineFields: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.md,
  },
  lineField: { minWidth: 80 },
  lineFieldLabel: { fontSize: fontSize.meta, color: text.tertiary, textTransform: 'uppercase', letterSpacing: 0.4 },
  lineFieldValue: { fontSize: fontSize.body, fontWeight: '600', color: text.primary, fontVariant: ['tabular-nums'] },
  noticeBand: { marginHorizontal: spacing.md, marginBottom: spacing.sm, padding: spacing.sm, borderRadius: 8 },
  noticeText: { fontSize: fontSize.caption, fontWeight: '600' },
  // Batch verification
  actionSection: {
    borderTopWidth: 1,
    borderTopColor: surface.border,
    padding: spacing.md,
    gap: spacing.sm,
  },
  actionSectionTitle: { fontSize: fontSize.caption, fontWeight: '700', color: text.secondary, textTransform: 'uppercase', letterSpacing: 0.6 },
  batchRow: { flexDirection: 'row', gap: spacing.sm, alignItems: 'center' },
  batchInput: {
    flex: 1,
    minHeight: controlSize.touchTarget,
    paddingHorizontal: spacing.md,
    borderWidth: 1,
    borderColor: surface.borderStrong,
    borderRadius: 8,
    backgroundColor: surface.raised,
    color: text.primary,
    fontSize: fontSize.body,
  },
  batchButton: {
    minHeight: controlSize.touchTarget,
    paddingHorizontal: spacing.md,
    borderRadius: 8,
    backgroundColor: action.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonDisabled: { backgroundColor: surface.sunken },
  batchButtonLabel: { color: action.primaryForeground, fontWeight: '700', fontSize: fontSize.body },
  verifyResult: {
    borderLeftWidth: 4,
    paddingLeft: spacing.md,
    gap: spacing.xs,
  },
  verifyResultLabel: { fontSize: fontSize.body, fontWeight: '700' },
  verifyReason: { fontSize: fontSize.caption, color: text.secondary },
  // Final check
  checkTable: { gap: 1, borderRadius: 8, overflow: 'hidden', borderWidth: 1, borderColor: surface.border },
  checkRowWrap: {
    flexDirection: 'row',
    backgroundColor: surface.raised,
    padding: spacing.sm,
    gap: spacing.sm,
  },
  checkField: { width: 72, fontSize: fontSize.caption, color: text.secondary, fontWeight: '600' },
  checkValue: { flex: 1, fontSize: fontSize.caption, color: text.primary, fontVariant: ['tabular-nums'] },
  checkCompletedNote: { fontSize: fontSize.caption, color: statusPalette.SAFE.foreground, fontWeight: '600', marginTop: spacing.sm },
  // Timeline
  timeline: { marginHorizontal: spacing.lg, paddingBottom: spacing.md },
  timelineRow: { flexDirection: 'row', gap: spacing.sm, paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: surface.divider },
  timelineTime: { width: 80, fontSize: fontSize.meta, color: text.tertiary, fontVariant: ['tabular-nums'] },
  timelineDot: { width: 10, height: 10, borderRadius: 5, borderWidth: 2, marginTop: 4 },
  timelineContent: { flex: 1, gap: 2 },
  timelineLabel: { fontSize: fontSize.body, fontWeight: '600', color: text.primary },
  timelineSummary: { fontSize: fontSize.caption, color: text.secondary },
  timelineReason: { fontSize: fontSize.caption },
  timelineEmpty: { marginHorizontal: spacing.lg, fontSize: fontSize.body, color: text.secondary },
  // Action bar
  actionBar: {
    borderTopWidth: 1,
    borderTopColor: surface.border,
    backgroundColor: surface.raised,
    padding: spacing.lg,
    gap: spacing.md,
  },
  nextLabel: { fontSize: fontSize.caption, color: text.secondary },
  primary: {
    minHeight: controlSize.touchTargetLarge,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: action.primary,
  },
  primaryDisabled: { backgroundColor: surface.sunken },
  primaryLabel: { color: action.primaryForeground, fontSize: fontSize.bodyLarge, fontWeight: '600' },
  primaryLabelDisabled: { color: text.tertiary },
  // Empty state
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl, gap: spacing.sm },
  emptyTitle: { marginTop: spacing.md, fontSize: fontSize.sectionTitle, fontWeight: '600', color: text.primary },
  emptyBody: { marginTop: spacing.sm, fontSize: fontSize.body, color: text.secondary, textAlign: 'center' },
});
