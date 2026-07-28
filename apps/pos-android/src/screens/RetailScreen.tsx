import {
  action,
  controlSize,
  deriveRetailPrimaryAction,
  fontSize,
  spacing,
  statusPalette,
  surface,
  text,
} from '@dawatrace/shared/design-system/index.js';
import {
  PosRetailClient,
  type RetailCatalogueItemDTO,
  type RetailTransactionDTO,
  type RetailTransactionLineDTO,
} from '@dawatrace/shared/retail/index.js';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

interface RetailScreenProps {
  readonly apiBaseUrl: string;
  readonly apiFetch: typeof fetch;
  readonly deviceId: string;
}

/** Tablet-native retail workspace. The footer is the stable location for the
 * next action and authoritative total; a transaction line never becomes a
 * dense desktop table. */
export function RetailScreen({ apiBaseUrl, apiFetch, deviceId }: RetailScreenProps) {
  const client = useMemo(
    () => new PosRetailClient(`${apiBaseUrl}/api/pos/retail`, { fetcher: apiFetch }),
    [apiBaseUrl, apiFetch],
  );
  const [storeId, setStoreId] = useState('');
  const [stores, setStores] = useState<
    readonly { id: string; name: string; location_type: string; status: string }[]
  >([]);
  const [transaction, setTransaction] = useState<RetailTransactionDTO | null>(null);
  const [results, setResults] = useState<readonly RetailCatalogueItemDTO[]>([]);
  const [barcode, setBarcode] = useState('');
  const [query, setQuery] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void client
      .stores()
      .then((loaded) => {
        const active = loaded.filter(
          (store) =>
            store.status === 'ACTIVE' &&
            ['STORE', 'PHARMACY', 'DISPENSARY'].includes(store.location_type),
        );
        setStores(active);
        setStoreId((current) => current || active[0]?.id || '');
      })
      .catch((cause: unknown) => setNotice(message(cause)));
  }, [client]);

  const run = async (operation: () => Promise<void>) => {
    setBusy(true);
    try {
      await operation();
      setNotice('');
    } catch (cause) {
      setNotice(message(cause));
    } finally {
      setBusy(false);
    }
  };

  const refreshTransaction = async (transactionId: string) => {
    setTransaction(await client.getTransaction(transactionId));
  };

  const start = () =>
    void run(async () => {
      if (!storeId) throw new Error('Select an active retail store before starting a sale.');
      setTransaction(await client.createDraft({ device_id: deviceId, store_id: storeId }));
      setResults([]);
      setBarcode('');
      setQuery('');
    });
  const scan = () =>
    void run(async () => {
      if (!transaction) throw new Error('Start a sale before scanning an item.');
      if (!barcode.trim()) throw new Error('Enter or scan a barcode.');
      await client.scan(transaction.id, {
        device_id: deviceId,
        barcode: barcode.trim(),
        quantity: '1.0000',
      });
      await refreshTransaction(transaction.id);
      setBarcode('');
    });
  const search = () =>
    void run(async () => {
      if (!storeId || !query.trim()) {
        setResults([]);
        return;
      }
      setResults(await client.search({ device_id: deviceId, store_id: storeId, query: query.trim() }));
    });
  const add = (item: RetailCatalogueItemDTO) =>
    void run(async () => {
      if (!transaction) throw new Error('Start a sale before adding an item.');
      await client.addLine(transaction.id, {
        device_id: deviceId,
        sku_id: item.sku_id,
        quantity: '1.0000',
      });
      await refreshTransaction(transaction.id);
    });
  const quantity = (line: RetailTransactionLineDTO, change: number) =>
    void run(async () => {
      if (!transaction) return;
      const next = Math.max(0, Number(line.quantity) + change);
      if (next === 0) {
        await client.removeLine(transaction.id, { device_id: deviceId, line_id: line.id });
      } else {
        await client.setQuantity(transaction.id, {
          device_id: deviceId,
          line_id: line.id,
          quantity: next.toFixed(4),
        });
      }
      await refreshTransaction(transaction.id);
    });
  const hold = () =>
    void run(async () => {
      if (transaction) {
        setTransaction(
          await client.hold(transaction.id, { device_id: deviceId, reason: 'Operator hold' }),
        );
      }
    });
  const resume = () =>
    void run(async () => {
      if (transaction) setTransaction(await client.resume(transaction.id, { device_id: deviceId }));
    });
  const preparePayment = () =>
    void run(async () => {
      if (transaction) {
        setTransaction(await client.readyForPayment(transaction.id, { device_id: deviceId }));
      }
    });

  const primary = deriveRetailPrimaryAction({
    state: transaction?.state ?? null,
    lineCount: transaction?.lines.length ?? 0,
    hasStore: Boolean(storeId),
  });
  const performPrimaryAction = () => {
    if (primary.kind === 'START_SALE') start();
    if (primary.kind === 'RESUME_SALE') resume();
    if (primary.kind === 'PREPARE_PAYMENT') preparePayment();
  };

  return (
    <View style={styles.root}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <View style={styles.headingRow}>
          <View style={styles.headingCopy}>
            <Text style={styles.title}>Retail sale</Text>
            <Text style={styles.muted}>Authoritative price and availability at the selected store.</Text>
          </View>
          {transaction ? <StateChip state={transaction.state} /> : null}
        </View>
        <View style={styles.safetyNote}>
          <Text style={styles.safetyNoteText}>
            Prescription medicines must be processed in Prescriptions. Retail medicine screening is
            not available in this pilot.
          </Text>
        </View>
        {notice ? (
          <View accessibilityLiveRegion="assertive" style={styles.notice}>
            <Text style={styles.noticeText}>{notice}</Text>
          </View>
        ) : null}

        <Section title="Store">
          <View style={styles.storeRow}>
            {stores.map((store) => {
              const selected = storeId === store.id;
              return (
                <Pressable
                  key={store.id}
                  accessibilityRole="button"
                  accessibilityState={{ selected, disabled: Boolean(transaction) }}
                  accessibilityLabel={`Use ${store.name} ${store.location_type}`}
                  disabled={Boolean(transaction)}
                  onPress={() => setStoreId(store.id)}
                  style={[styles.store, selected && styles.storeSelected]}
                >
                  <Text style={selected ? styles.storeTextSelected : styles.storeText}>{store.name}</Text>
                  <Text style={styles.small}>{store.location_type}</Text>
                </Pressable>
              );
            })}
          </View>
        </Section>

        <Section title="Scan or search">
          <Text style={styles.sectionHint}>Barcode is fastest. Search returns only priced, sellable items.</Text>
          <View style={styles.fieldRow}>
            <TextInput
              value={barcode}
              onChangeText={setBarcode}
              onSubmitEditing={scan}
              editable={!busy && transaction?.state === 'DRAFT'}
              placeholder="Scan barcode"
              accessibilityLabel="Barcode"
              style={styles.input}
            />
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Add scanned item"
              onPress={scan}
              disabled={busy || !transaction || transaction.state !== 'DRAFT' || !barcode.trim()}
              style={({ pressed }) => [styles.secondary, pressed && styles.pressed]}
            >
              <Text style={styles.secondaryText}>Add</Text>
            </Pressable>
          </View>
          <View style={styles.fieldRow}>
            <TextInput
              value={query}
              onChangeText={setQuery}
              onSubmitEditing={search}
              editable={!busy && Boolean(storeId)}
              placeholder="Name, SKU or barcode"
              accessibilityLabel="Search the catalogue"
              style={styles.input}
            />
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Search catalogue"
              onPress={search}
              disabled={busy || !storeId}
              style={({ pressed }) => [styles.secondary, pressed && styles.pressed]}
            >
              <Text style={styles.secondaryText}>Search</Text>
            </Pressable>
          </View>
          {results.map((item) => (
            <Pressable
              key={item.sku_id}
              accessibilityRole="button"
              accessibilityLabel={`Add ${item.display_name}, ${money(item.unit_price, item.currency)}`}
              disabled={busy || !transaction || transaction.state !== 'DRAFT' || item.stock_state === 'OUT_OF_STOCK'}
              onPress={() => add(item)}
              style={({ pressed }) => [styles.result, pressed && styles.pressed]}
            >
              <View style={styles.resultCopy}>
                <Text style={styles.resultName}>{item.display_name}</Text>
                <Text style={styles.small}>
                  {item.sku_code} · {item.available_quantity} {item.unit} ·{' '}
                  {item.stock_state.replace(/_/g, ' ').toLowerCase()}
                </Text>
              </View>
              <Text style={styles.resultPrice}>{money(item.unit_price, item.currency)}</Text>
            </Pressable>
          ))}
        </Section>

        <Section title={transaction ? transaction.transaction_number : 'Current basket'}>
          {transaction?.lines.length ? (
            transaction.lines.map((line) => (
              <RetailLine
                key={line.id}
                line={line}
                editable={!busy && transaction.state === 'DRAFT'}
                onDecrease={() => quantity(line, -1)}
                onIncrease={() => quantity(line, 1)}
              />
            ))
          ) : (
            <View style={styles.emptyState}>
              <Text style={styles.emptyTitle}>No items are in this sale.</Text>
              <Text style={styles.muted}>Scan a barcode or search for an item.</Text>
            </View>
          )}
        </Section>
      </ScrollView>

      <View style={styles.footer}>
        <View style={styles.totalCopy}>
          <Text style={styles.small}>{transaction?.state.replace(/_/g, ' ') ?? 'No active sale'}</Text>
          <Text style={styles.total}>
            {transaction ? money(transaction.total, transaction.currency) : '—'}
          </Text>
        </View>
        <View style={styles.footerActions}>
          {transaction?.state === 'DRAFT' ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Hold sale"
              disabled={busy}
              onPress={hold}
              style={({ pressed }) => [styles.secondary, pressed && styles.pressed]}
            >
              <Text style={styles.secondaryText}>Hold</Text>
            </Pressable>
          ) : null}
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={primary.label}
            accessibilityHint={primary.detail}
            accessibilityState={{ disabled: busy || !primary.enabled }}
            disabled={busy || !primary.enabled}
            onPress={performPrimaryAction}
            style={({ pressed }) => [
              styles.primary,
              styles.primaryFooter,
              (busy || !primary.enabled) && styles.disabled,
              pressed && primary.enabled && styles.pressedPrimary,
            ]}
          >
            <Text style={styles.primaryText}>{primary.label}</Text>
          </Pressable>
        </View>
      </View>
    </View>
  );
}

function RetailLine({
  line,
  editable,
  onDecrease,
  onIncrease,
}: {
  readonly line: RetailTransactionLineDTO;
  readonly editable: boolean;
  readonly onDecrease: () => void;
  readonly onIncrease: () => void;
}) {
  return (
    <View style={styles.line}>
      <View style={styles.lineInfo}>
        <Text style={styles.resultName}>{line.description_snapshot}</Text>
        <Text style={styles.small}>
          {line.sku_code} · {money(line.unit_price, line.currency)} / {line.unit}
        </Text>
        <Text style={styles.small}>
          Stock {line.inventory_context.stock_state.replace(/_/g, ' ').toLowerCase()} · Price{' '}
          {line.price_snapshot.source ?? 'authoritative source'}
        </Text>
      </View>
      <View style={styles.lineControls} accessibilityLabel={`Quantity for ${line.description_snapshot}`}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Decrease quantity for ${line.description_snapshot}`}
          disabled={!editable}
          onPress={onDecrease}
          style={({ pressed }) => [styles.quantityButton, pressed && styles.pressed]}
        >
          <Text style={styles.quantityLabel}>−</Text>
        </Pressable>
        <Text style={styles.quantity}>{line.quantity}</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Increase quantity for ${line.description_snapshot}`}
          disabled={!editable}
          onPress={onIncrease}
          style={({ pressed }) => [styles.quantityButton, pressed && styles.pressed]}
        >
          <Text style={styles.quantityLabel}>+</Text>
        </Pressable>
      </View>
      <Text style={styles.resultPrice}>{money(line.line_total, line.currency)}</Text>
    </View>
  );
}

function Section({ title, children }: { readonly title: string; readonly children: React.ReactNode }) {
  return (
    <View style={styles.card}>
      <Text style={styles.section}>{title}</Text>
      {children}
    </View>
  );
}

function StateChip({ state }: { readonly state: string }) {
  const isHeld = state === 'HELD';
  return (
    <View style={[styles.chip, isHeld ? styles.chipHeld : styles.chipNeutral]}>
      <Text style={[styles.chipLabel, isHeld ? styles.chipHeldLabel : styles.chipNeutralLabel]}>
        {state.replace(/_/g, ' ')}
      </Text>
    </View>
  );
}

function money(amount: string, currency: string) {
  return `${currency} ${Number(amount).toLocaleString('en-KE', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function message(cause: unknown) {
  return cause instanceof Error ? cause.message : String(cause);
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: surface.page },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: 124 },
  headingRow: { flexDirection: 'row', gap: spacing.md, alignItems: 'flex-start' },
  headingCopy: { flex: 1 },
  title: { fontSize: fontSize.screenTitle, color: text.primary, fontWeight: '700' },
  muted: { color: text.secondary, fontSize: fontSize.body },
  card: {
    borderWidth: 1,
    borderColor: surface.border,
    borderRadius: 12,
    padding: spacing.md,
    gap: spacing.sm,
    backgroundColor: surface.raised,
  },
  section: { fontWeight: '700', fontSize: fontSize.bodyLarge, color: text.primary },
  sectionHint: { color: text.secondary, fontSize: fontSize.caption },
  safetyNote: {
    padding: spacing.sm,
    borderLeftWidth: 3,
    borderLeftColor: statusPalette.ACTION_REQUIRED.accent,
    backgroundColor: statusPalette.ACTION_REQUIRED.surface,
  },
  safetyNoteText: { color: statusPalette.ACTION_REQUIRED.foreground, fontSize: fontSize.caption, lineHeight: 18 },
  notice: {
    padding: spacing.sm,
    borderLeftWidth: 3,
    borderLeftColor: statusPalette.BLOCKING.accent,
    backgroundColor: statusPalette.BLOCKING.surface,
  },
  noticeText: { color: statusPalette.BLOCKING.foreground, fontWeight: '700' },
  storeRow: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
  store: {
    minHeight: controlSize.touchTarget,
    borderWidth: 1,
    borderColor: surface.border,
    borderRadius: 8,
    padding: spacing.sm,
    backgroundColor: surface.raised,
  },
  storeSelected: { backgroundColor: statusPalette.PROCESSING.surface, borderColor: statusPalette.PROCESSING.border },
  storeText: { color: text.primary, fontWeight: '600' },
  storeTextSelected: { color: statusPalette.PROCESSING.foreground, fontWeight: '700' },
  fieldRow: { flexDirection: 'row', gap: spacing.sm },
  input: {
    flex: 1,
    minHeight: controlSize.touchTarget,
    borderWidth: 1,
    borderColor: surface.borderStrong,
    borderRadius: 8,
    paddingHorizontal: spacing.md,
    backgroundColor: surface.raised,
    color: text.primary,
    fontSize: fontSize.body,
  },
  primary: {
    minHeight: controlSize.touchTarget,
    borderRadius: 8,
    backgroundColor: action.primary,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.md,
  },
  primaryFooter: { minWidth: 156 },
  primaryText: { color: action.primaryForeground, fontWeight: '700', fontSize: fontSize.body },
  secondary: {
    minHeight: controlSize.touchTarget,
    borderWidth: 1,
    borderColor: action.secondaryBorder,
    borderRadius: 8,
    paddingHorizontal: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: action.secondary,
  },
  secondaryText: { color: text.primary, fontWeight: '700' },
  disabled: { backgroundColor: action.disabled, opacity: 1 },
  pressed: { opacity: 0.76 },
  pressedPrimary: { backgroundColor: action.primaryPressed },
  result: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: spacing.sm,
    paddingVertical: spacing.md,
    borderTopWidth: 1,
    borderTopColor: surface.border,
  },
  resultCopy: { flex: 1 },
  resultName: { color: text.primary, fontWeight: '700', fontSize: fontSize.body },
  resultPrice: {
    color: text.primary,
    fontWeight: '700',
    alignSelf: 'center',
    fontVariant: ['tabular-nums'],
  },
  small: { color: text.secondary, fontSize: fontSize.caption },
  line: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: surface.border,
    paddingVertical: spacing.md,
  },
  lineInfo: { flex: 1, gap: 2 },
  lineControls: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  quantityButton: {
    minWidth: controlSize.touchTarget,
    minHeight: controlSize.touchTarget,
    borderWidth: 1,
    borderColor: action.secondaryBorder,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: action.secondary,
  },
  quantityLabel: { color: text.primary, fontSize: fontSize.bodyLarge, fontWeight: '700' },
  quantity: { minWidth: 30, textAlign: 'center', color: text.primary, fontWeight: '700', fontVariant: ['tabular-nums'] },
  emptyState: { paddingVertical: spacing.xl, gap: spacing.xs, alignItems: 'center' },
  emptyTitle: { color: text.primary, fontWeight: '700', fontSize: fontSize.bodyLarge },
  footer: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: surface.raised,
    borderTopWidth: 1,
    borderTopColor: surface.border,
    padding: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  totalCopy: { flex: 1 },
  total: { fontSize: fontSize.sectionTitle, fontWeight: '700', color: text.primary, fontVariant: ['tabular-nums'] },
  footerActions: { flexDirection: 'row', gap: spacing.sm, alignItems: 'center' },
  chip: { borderWidth: 1, borderRadius: 999, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs },
  chipNeutral: { backgroundColor: statusPalette.INFORMATION.surface, borderColor: statusPalette.INFORMATION.border },
  chipHeld: { backgroundColor: statusPalette.ACTION_REQUIRED.surface, borderColor: statusPalette.ACTION_REQUIRED.border },
  chipLabel: { fontSize: fontSize.caption, fontWeight: '700' },
  chipNeutralLabel: { color: statusPalette.INFORMATION.foreground },
  chipHeldLabel: { color: statusPalette.ACTION_REQUIRED.foreground },
});
