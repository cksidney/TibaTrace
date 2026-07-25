import {
  STAGE_STATUS,
  controlSize,
  deriveStages,
  fontSize,
  nextAction,
  spacing,
  statusPalette,
  surface,
  text,
} from '@dawatrace/shared/design-system/index.js';
import type { StageView } from '@dawatrace/shared/design-system/index.js';
import type { DispensingEpisodeDTO } from '@dawatrace/shared/dispensing/index.js';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ClinicalSummaryCard, PatientBanner } from '../components/tibatrace/ClinicalSummaryCard.js';
import type { AndroidClinicalSummary } from '../components/tibatrace/ClinicalSummaryCard.js';

/**
 * Android dispensing episode.
 *
 * Touch-first, but driven by exactly the same shared derivation as Windows:
 * `deriveStages` and the gate come from the server's episode state, so the two
 * clients cannot disagree about whether supply is permitted.
 */
export function DispensingScreen({
  episode,
  clinical,
  gateBlockedReason,
  canConfirmCollection,
  onConfirmCollection,
  onReviewFinding,
}: {
  readonly episode: DispensingEpisodeDTO | null;
  readonly clinical: AndroidClinicalSummary;
  readonly gateBlockedReason: string;
  readonly canConfirmCollection: boolean;
  readonly onConfirmCollection?: () => void;
  readonly onReviewFinding?: () => void;
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
        <Text style={styles.emptyTitle}>No prescription loaded</Text>
        <Text style={styles.emptyBody}>Scan or search for a prescription to begin dispensing.</Text>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <PatientBanner
        fullName={episode.patient}
        reference={episode.dispensing_number}
        allergyStatus="UNKNOWN"
      />

      <ScrollView contentContainerStyle={styles.scroll}>
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

function StageRow({ stage }: { readonly stage: StageView }) {
  const palette = statusPalette[STAGE_STATUS[stage.state]];
  return (
    <View
      accessibilityLabel={`Step ${stage.step}, ${stage.label}, ${stage.state
        .replace(/_/g, ' ')
        .toLowerCase()}${stage.blockedReason ? `. ${stage.blockedReason}` : ''}`}
      style={[styles.stageRow, { borderLeftColor: palette.accent }]}
    >
      <Text style={styles.stageStep}>{stage.step}</Text>
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
  scroll: { paddingBottom: spacing.xxxl },
  sectionTitle: {
    marginHorizontal: spacing.lg,
    marginTop: spacing.sm,
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
    color: text.secondary,
    fontVariant: ['tabular-nums'],
    minWidth: 16,
  },
  stageText: { flexShrink: 1 },
  stageLabel: { fontSize: fontSize.body, fontWeight: '600', color: text.primary },
  stageReason: { marginTop: 2, fontSize: fontSize.caption, lineHeight: fontSize.caption * 1.4 },
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
    backgroundColor: '#12854A',
  },
  primaryDisabled: { backgroundColor: surface.sunken },
  primaryLabel: { color: text.inverse, fontSize: fontSize.bodyLarge, fontWeight: '600' },
  primaryLabelDisabled: { color: text.tertiary },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  emptyTitle: { fontSize: fontSize.sectionTitle, fontWeight: '600', color: text.primary },
  emptyBody: { marginTop: spacing.sm, fontSize: fontSize.body, color: text.secondary, textAlign: 'center' },
});
