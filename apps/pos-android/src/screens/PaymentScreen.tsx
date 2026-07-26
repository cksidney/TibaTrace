import {
  controlSize,
  fontSize,
  spacing,
  statusPalette,
  surface,
  text,
} from '@dawatrace/shared/design-system/index.js';
import type { PaymentState, PaymentTenderType } from '@dawatrace/shared/dispensing/index.js';
import { TENDER_OPTIONS, paymentPermitsSupply } from '@dawatrace/shared/dispensing/index.js';
import { useState } from 'react';

import { liveRegionFor } from '../components/tibatrace/liveRegion';
import { TibaTraceBrand } from '../components/tibatrace/TibaTraceBrand';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

/**
 * Android payment.
 *
 * Tender availability, status wording and the part-payment rule are identical
 * to Windows -- both read the same shared contract. A tender whose settlement
 * path does not exist is disabled with its reason shown, never presented as
 * working.
 */



export function PaymentScreen({
  paymentState,
  amountDue,
  amountSettled,
  canTakePayment,
  blockedReason,
  busy,
  onTakePayment,
}: {
  readonly paymentState: PaymentState;
  readonly amountDue: string | null;
  readonly amountSettled: string | null;
  readonly canTakePayment: boolean;
  readonly blockedReason: string;
  readonly busy: boolean;
  readonly onTakePayment: (tender: PaymentTenderType, amount: string, reference: string) => void;
}) {
  const [tender, setTender] = useState<PaymentTenderType | 'SPLIT'>('CASH');
  const [amount, setAmount] = useState(amountDue ?? '');
  const [submitted, setSubmitted] = useState(false);

  const priced = amountDue !== null && amountSettled !== null;
  const remaining = priced ? Number(amountDue) - Number(amountSettled) : null;
  const selected = TENDER_OPTIONS.find((option) => option.type === tender);
  const enabled = priced && canTakePayment && !busy && !submitted && (selected?.available ?? false);

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.root}>
      <TibaTraceBrand />
      <Text style={styles.heading}>Payment</Text>

      <View style={styles.amounts}>
        <Amount label="Due" value={amountDue ?? 'Not priced'} />
        <Amount label="Settled" value={amountSettled ?? '—'} />
        <Amount
          label="Remaining"
          value={remaining === null ? '—' : remaining.toFixed(2)}
          emphasis={remaining !== null && remaining > 0}
        />
      </View>

      {/* Part-payment is the state most likely to be misread as "enough to hand
          the medicine over", so it is stated in full rather than implied. */}
      {paymentState === 'PARTIALLY_PAID' ? (
        <Notice
          status="ACTION_REQUIRED"
          message="Partially paid. The balance must be settled before medicine can be supplied."
        />
      ) : null}

      {blockedReason ? <Notice status="BLOCKING" message={blockedReason} /> : null}

      {!priced ? (
        <Notice
          status="DISABLED"
          message="No payment intent is open for this episode, so there is no authoritative amount to collect."
        />
      ) : null}

      <Text style={styles.label}>Tender</Text>
      <View style={styles.tenders}>
        {TENDER_OPTIONS.map((option) => (
          <Pressable
            key={option.type}
            accessibilityRole="button"
            accessibilityState={{ disabled: !option.available, selected: tender === option.type }}
            accessibilityHint={option.blocker}
            disabled={!option.available}
            onPress={() => setTender(option.type)}
            style={[
              styles.tender,
              tender === option.type && styles.tenderSelected,
              !option.available && styles.tenderDisabled,
            ]}
          >
            <Text style={[styles.tenderLabel, !option.available && styles.tenderLabelDisabled]}>
              {option.label}
            </Text>
          </Pressable>
        ))}
      </View>

      {selected && !selected.available && selected.blocker ? (
        <Text style={styles.blockerText}>{selected.blocker}</Text>
      ) : null}

      <Text style={styles.label}>Amount</Text>
      <TextInput
        value={amount}
        onChangeText={setAmount}
        keyboardType="decimal-pad"
        accessibilityLabel="Payment amount"
        style={styles.input}
      />

      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: !enabled }}
        disabled={!enabled}
        onPress={() => {
          // Latches so a second tap cannot become a second charge.
          setSubmitted(true);
          onTakePayment(tender as PaymentTenderType, amount, '');
        }}
        style={[styles.primary, !enabled && styles.primaryDisabled]}
      >
        <Text style={[styles.primaryLabel, !enabled && styles.primaryLabelDisabled]}>
          {busy ? 'Confirming payment…' : 'Take payment'}
        </Text>
      </Pressable>

      {paymentPermitsSupply(paymentState) ? (
        <Text style={styles.footnote}>
          Payment permits commercial completion. Medicine is supplied only when collection is
          confirmed.
        </Text>
      ) : null}
    </ScrollView>
  );
}

function Amount({
  label,
  value,
  emphasis,
}: {
  readonly label: string;
  readonly value: string;
  readonly emphasis?: boolean;
}) {
  return (
    <View style={styles.amount}>
      <Text style={styles.amountLabel}>{label}</Text>
      <Text
        style={[
          styles.amountValue,
          emphasis ? { color: statusPalette.ACTION_REQUIRED.foreground } : null,
        ]}
      >
        {value}
      </Text>
    </View>
  );
}

function Notice({
  status,
  message,
}: {
  readonly status: 'BLOCKING' | 'ACTION_REQUIRED' | 'DISABLED';
  readonly message: string;
}) {
  const palette = statusPalette[status];
  return (
    <View
      accessibilityLiveRegion={liveRegionFor(status)}
      style={[styles.notice, { backgroundColor: palette.surface, borderLeftColor: palette.accent }]}
    >
      <Text style={[styles.noticeText, { color: palette.foreground }]}>{message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1 },
  root: { padding: spacing.lg, gap: spacing.md },
  heading: { fontSize: fontSize.screenTitle, fontWeight: '700', color: text.primary },
  amounts: { flexDirection: 'row', gap: spacing.lg },
  amount: { flex: 1 },
  amountLabel: { fontSize: fontSize.meta, color: text.tertiary, textTransform: 'uppercase' },
  amountValue: {
    fontSize: fontSize.medicineName,
    fontWeight: '600',
    color: text.primary,
    fontVariant: ['tabular-nums'],
  },
  label: {
    marginTop: spacing.md,
    fontSize: fontSize.caption,
    color: text.tertiary,
    textTransform: 'uppercase',
  },
  tenders: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  tender: {
    minHeight: controlSize.touchTarget,
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: surface.borderStrong,
    backgroundColor: surface.raised,
  },
  tenderSelected: { borderColor: statusPalette.INFORMATION.accent, backgroundColor: statusPalette.INFORMATION.surface },
  tenderDisabled: { backgroundColor: surface.sunken, borderColor: surface.border },
  tenderLabel: { fontSize: fontSize.body, fontWeight: '600', color: text.primary },
  tenderLabelDisabled: { color: text.tertiary },
  blockerText: { fontSize: fontSize.caption, color: text.secondary },
  input: {
    minHeight: controlSize.touchTarget,
    borderWidth: 1,
    borderColor: surface.borderStrong,
    borderRadius: 10,
    paddingHorizontal: spacing.md,
    fontSize: fontSize.bodyLarge,
    fontVariant: ['tabular-nums'],
  },
  primary: {
    marginTop: spacing.lg,
    minHeight: controlSize.touchTargetLarge,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#12854A',
  },
  primaryDisabled: { backgroundColor: surface.sunken },
  primaryLabel: { color: text.inverse, fontSize: fontSize.bodyLarge, fontWeight: '600' },
  primaryLabelDisabled: { color: text.tertiary },
  notice: {
    borderLeftWidth: 4,
    borderRadius: 8,
    padding: spacing.md,
  },
  noticeText: { fontSize: fontSize.body, lineHeight: fontSize.body * 1.45 },
  footnote: { fontSize: fontSize.caption, color: text.secondary },
});
