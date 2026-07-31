import {
  ALLERGY_STATUS,
  CLINICAL_STATUS,
  controlSize,
  fontSize,
  glyphFor,
  spacing,
  statusPalette,
  surface,
  text,
} from '@dawatrace/shared/design-system/index.js';

import { liveRegionFor } from './liveRegion';
import type {
  AllergyStatus,
  ClinicalStatus,
  ConnectivityState,
} from '@dawatrace/shared/design-system/index.js';
import { Pressable, StyleSheet, Text, View } from 'react-native';

/**
 * Android clinical summary.
 *
 * Shares the semantics of the Windows rail -- the same statuses, the same
 * blocking rules, the same headline derivation -- but renders natively for
 * touch. Android must never apply weaker clinical rules than Windows, which is
 * why the decision logic lives in the shared package and only presentation
 * lives here.
 *
 * On a handheld the summary sits directly below the patient banner so the
 * blocker is the first thing read, without scrolling.
 */

export interface AndroidClinicalSummary {
  readonly safeToProceed: boolean;
  readonly screened: boolean;
  readonly stale: boolean;
  readonly blockingCount: number;
  readonly connectivity: ConnectivityState;
  readonly headlineTitle: string;
  readonly headlineDetail: string;
  readonly headlineStatus: ClinicalStatus;
}

export function ClinicalSummaryCard({
  summary,
  onReview,
}: {
  readonly summary: AndroidClinicalSummary;
  readonly onReview?: () => void;
}) {
  const palette = statusPalette[summary.headlineStatus];
  const meta = CLINICAL_STATUS[summary.headlineStatus];

  return (
    <View
      accessibilityRole="summary"
      accessibilityLiveRegion={liveRegionFor(summary.headlineStatus)}
      style={[
        styles.card,
        { backgroundColor: palette.surface, borderColor: palette.border, borderTopColor: palette.accent },
      ]}
    >
      <Text style={[styles.title, { color: palette.foreground }]}>{summary.headlineTitle}</Text>
      <Text style={styles.detail}>{summary.headlineDetail}</Text>

      {meta.blocksProgression && onReview ? (
        // An explicit, labelled control. Critical clinical actions are never
        // reachable only by swipe.
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Review blocking finding"
          onPress={onReview}
          style={({ pressed }) => [styles.action, pressed && styles.actionPressed]}
        >
          <Text style={styles.actionLabel}>Review finding</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

/**
 * Compact patient banner.
 *
 * Allergy status is always present and never rendered as neutral when unknown,
 * matching Windows exactly.
 */
export function PatientBanner({
  fullName,
  reference,
  allergyStatus,
}: {
  readonly fullName: string;
  readonly reference: string;
  readonly allergyStatus: AllergyStatus;
}) {
  const allergy = ALLERGY_STATUS[allergyStatus];
  const palette = statusPalette[allergy.status];

  return (
    <View style={styles.banner}>
      <View style={styles.bannerText}>
        <Text style={styles.patientName} numberOfLines={1}>
          {fullName}
        </Text>
        <Text style={styles.reference}>{reference}</Text>
      </View>
      <View
        accessibilityLabel={allergy.label}
        style={[styles.badge, { backgroundColor: palette.surface, borderColor: palette.border }]}
      >
        <Text style={[styles.badgeGlyph, { color: palette.foreground }]} accessible={false}>
          {glyphFor(allergy.status)}
        </Text>
        <Text style={[styles.badgeLabel, { color: palette.foreground }]}>{allergy.label}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderTopWidth: 4,
    borderRadius: 12,
    padding: spacing.lg,
    margin: spacing.lg,
  },
  title: {
    fontSize: fontSize.sectionTitle,
    fontWeight: '700',
  },
  detail: {
    marginTop: spacing.sm,
    fontSize: fontSize.body,
    lineHeight: fontSize.body * 1.45,
    color: text.secondary,
  },
  action: {
    marginTop: spacing.lg,
    // Meets the accessible touch-target guidance; a mis-tap on a clinical
    // control is expensive.
    minHeight: controlSize.touchTarget,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: surface.inverse,
    paddingHorizontal: spacing.lg,
  },
  actionPressed: {
    opacity: 0.85,
  },
  actionLabel: {
    color: text.inverse,
    fontSize: fontSize.bodyLarge,
    fontWeight: '600',
  },
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    backgroundColor: surface.raised,
    borderBottomWidth: 1,
    borderBottomColor: surface.border,
  },
  bannerText: {
    flexShrink: 1,
  },
  patientName: {
    fontSize: fontSize.medicineName,
    fontWeight: '600',
    color: text.primary,
  },
  reference: {
    fontSize: fontSize.caption,
    color: text.secondary,
    fontVariant: ['tabular-nums'],
  },
  badge: {
    marginLeft: 'auto',
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  badgeGlyph: {
    fontSize: fontSize.caption,
    fontWeight: '700',
  },
  badgeLabel: {
    fontSize: fontSize.caption,
    fontWeight: '600',
  },
});
