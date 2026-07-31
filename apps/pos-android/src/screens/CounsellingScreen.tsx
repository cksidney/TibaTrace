import {
  action,
  controlSize,
  fontSize,
  spacing,
  statusPalette,
  surface,
  text,
} from '@dawatrace/shared/design-system/index.js';
import { formatInstant } from '@dawatrace/shared/clinical/index.js';
import type { CounsellingRecordRequest } from '@dawatrace/shared/dispensing/index.js';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';

import { readableColumn } from '../components/tibatrace/layout';
import { TibaTraceBrand } from '../components/tibatrace/TibaTraceBrand';

/**
 * Android counselling.
 *
 * Identical rules to Windows: every topic starts off, and the panel always
 * sends an explicit value for each. The server defaults an omitted counselling
 * flag to true, so a partial body would silently record that topics were
 * covered when they were not.
 */

const TOPICS = [
  { key: 'medicine_explained', label: 'Medicine and purpose explained' },
  { key: 'dosage_explained', label: 'Dosage and frequency explained' },
  { key: 'storage_explained', label: 'Storage explained' },
  { key: 'side_effects_discussed', label: 'Side effects discussed' },
  { key: 'interaction_advice_given', label: 'Interaction advice given' },
  { key: 'patient_acknowledged', label: 'Patient acknowledged understanding' },
] as const;

type TopicKey = (typeof TOPICS)[number]['key'];

export function CounsellingScreen({
  counsellingStatus,
  busy,
  onRecord,
}: {
  readonly counsellingStatus: string;
  readonly busy: boolean;
  readonly onRecord: (request: CounsellingRecordRequest) => void;
}) {
  const [checked, setChecked] = useState<Record<TopicKey, boolean>>({
    medicine_explained: false,
    dosage_explained: false,
    storage_explained: false,
    side_effects_discussed: false,
    interaction_advice_given: false,
    patient_acknowledged: false,
  });
  const [notes, setNotes] = useState('');
  const complete = counsellingStatus === 'COMPLETED';

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={[styles.root, readableColumn]}>
      <TibaTraceBrand />
      <View style={styles.header}>
        <Text style={styles.heading}>Counselling</Text>
        <View
          style={[
            styles.badge,
            {
              backgroundColor: complete
                ? statusPalette.COMPLETED.surface
                : statusPalette.ACTION_REQUIRED.surface,
            },
          ]}
        >
          <Text
            style={{
              fontSize: fontSize.caption,
              fontWeight: '600',
              color: complete
                ? statusPalette.COMPLETED.foreground
                : statusPalette.ACTION_REQUIRED.foreground,
            }}
          >
            {complete ? 'Recorded' : 'Not recorded'}
          </Text>
        </View>
      </View>

      {TOPICS.map((topic) => (
        <View key={topic.key} style={styles.row}>
          <Text style={styles.rowLabel}>{topic.label}</Text>
          <Switch
            accessibilityLabel={topic.label}
            value={checked[topic.key]}
            onValueChange={(value) => setChecked((prev) => ({ ...prev, [topic.key]: value }))}
          />
        </View>
      ))}

      <Text style={styles.label}>Notes</Text>
      <TextInput
        value={notes}
        onChangeText={setNotes}
        multiline
        numberOfLines={4}
        accessibilityLabel="Counselling notes"
        style={styles.notes}
      />

      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: busy }}
        disabled={busy}
        // Always sends every flag explicitly, never a partial body.
        onPress={() => onRecord({ ...checked, notes })}
        style={[styles.primary, busy && styles.primaryDisabled]}
      >
        <Text style={[styles.primaryLabel, busy && styles.primaryLabelDisabled]}>
          {busy ? 'Recording…' : 'Record counselling'}
        </Text>
      </Pressable>
    </ScrollView>
  );
}

/**
 * Android collection.
 *
 * Supply and collection stay separate facts: paying for medicine is not
 * receiving it. Confirming here is what posts the inventory movement.
 */
export function CollectionScreen({
  canConfirm,
  blockedReason,
  collectedAt,
  collectorName,
  busy,
  onConfirm,
}: {
  readonly canConfirm: boolean;
  readonly blockedReason: string;
  readonly collectedAt: string | null;
  readonly collectorName: string;
  readonly busy: boolean;
  readonly onConfirm: (name: string, idNumber: string, relationship: string) => void;
}) {
  const [name, setName] = useState('');
  const [idNumber, setIdNumber] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const enabled = canConfirm && !busy && !submitted && name.trim().length > 0;

  if (collectedAt) {
    return (
      <View style={styles.root}>
        <TibaTraceBrand />
        <Text style={styles.heading}>Collection</Text>
        <Text style={styles.body}>
          Collected by {collectorName || 'unrecorded collector'} at {formatInstant(collectedAt)}.
        </Text>
      </View>
    );
  }

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={[styles.root, readableColumn]}>
      <TibaTraceBrand />
      <Text style={styles.heading}>Collection</Text>

      {blockedReason ? (
        <View
          accessibilityLiveRegion="assertive"
          style={[
            styles.notice,
            {
              backgroundColor: statusPalette.BLOCKING.surface,
              borderLeftColor: statusPalette.BLOCKING.accent,
            },
          ]}
        >
          <Text style={{ color: statusPalette.BLOCKING.foreground, fontSize: fontSize.body }}>
            {blockedReason}
          </Text>
        </View>
      ) : null}

      <Text style={styles.label}>Collector name</Text>
      <TextInput
        value={name}
        onChangeText={setName}
        accessibilityLabel="Collector name"
        style={styles.input}
      />

      <Text style={styles.label}>Identity number</Text>
      <TextInput
        value={idNumber}
        onChangeText={setIdNumber}
        accessibilityLabel="Collector identity number"
        style={styles.input}
      />

      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: !enabled }}
        disabled={!enabled}
        onPress={() => {
          // Latches so a second tap cannot post the supply twice.
          setSubmitted(true);
          onConfirm(name.trim(), idNumber.trim(), 'SELF');
        }}
        style={[styles.primary, !enabled && styles.primaryDisabled]}
      >
        <Text style={[styles.primaryLabel, !enabled && styles.primaryLabelDisabled]}>
          {busy ? 'Confirming…' : 'Confirm collection'}
        </Text>
      </Pressable>

      <Text style={styles.footnote}>
        Confirming collection posts the inventory movement. It cannot be undone from this screen.
      </Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1 },
  root: { padding: spacing.lg, gap: spacing.md },
  header: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  heading: { fontSize: fontSize.screenTitle, fontWeight: '700', color: text.primary },
  body: { fontSize: fontSize.body, color: text.secondary },
  badge: { marginLeft: 'auto', borderRadius: 999, paddingHorizontal: spacing.md, paddingVertical: 4 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    minHeight: controlSize.touchTarget,
    borderBottomWidth: 1,
    borderBottomColor: surface.divider,
  },
  rowLabel: { flex: 1, fontSize: fontSize.body, color: text.primary },
  label: {
    marginTop: spacing.md,
    fontSize: fontSize.caption,
    color: text.tertiary,
    textTransform: 'uppercase',
  },
  input: {
    minHeight: controlSize.touchTarget,
    borderWidth: 1,
    borderColor: surface.borderStrong,
    borderRadius: 10,
    paddingHorizontal: spacing.md,
    fontSize: fontSize.bodyLarge,
  },
  notes: {
    minHeight: 96,
    borderWidth: 1,
    borderColor: surface.borderStrong,
    borderRadius: 10,
    padding: spacing.md,
    fontSize: fontSize.body,
    textAlignVertical: 'top',
  },
  primary: {
    marginTop: spacing.lg,
    minHeight: controlSize.touchTargetLarge,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: action.primary,
  },
  primaryDisabled: { backgroundColor: surface.sunken },
  primaryLabel: { color: text.inverse, fontSize: fontSize.bodyLarge, fontWeight: '600' },
  primaryLabelDisabled: { color: text.tertiary },
  notice: { borderLeftWidth: 4, borderRadius: 8, padding: spacing.md },
  footnote: { fontSize: fontSize.caption, color: text.secondary },
});
